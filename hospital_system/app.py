import os
import sqlite3
from datetime import date, datetime
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, session, g, jsonify, abort)

DB_PATH = "hospital.db"
# Secrets are read from environment variables so nothing sensitive is committed.
# The defaults below are for local demo use only.
STAFF_PASSWORD = os.environ.get("CAREQUEUE_STAFF_PASSWORD", "admin123")

app = Flask(__name__)
app.secret_key = os.environ.get("CAREQUEUE_SECRET_KEY", "dev-only-change-me")


# ---------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS departments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT UNIQUE NOT NULL,
    total_beds    INTEGER DEFAULT 0,
    occupied_beds INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS doctors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    department_id INTEGER NOT NULL,
    room          TEXT,
    avg_minutes   INTEGER DEFAULT 10,
    available     INTEGER DEFAULT 1,
    FOREIGN KEY (department_id) REFERENCES departments(id)
);
CREATE TABLE IF NOT EXISTS patients (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    phone      TEXT NOT NULL,
    age        INTEGER,
    gender     TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS appointments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  INTEGER NOT NULL,
    doctor_id   INTEGER NOT NULL,
    date        TEXT NOT NULL,
    token_no    INTEGER NOT NULL,
    reason      TEXT,
    status      TEXT NOT NULL DEFAULT 'waiting',  -- waiting|in_progress|done|cancelled|no_show
    created_at  TEXT,
    called_at   TEXT,
    finished_at TEXT,
    UNIQUE(doctor_id, date, token_no)
);
"""

SEED_DEPARTMENTS = [
    ("General Medicine", 40), ("Pediatrics", 20), ("Cardiology", 15),
    ("Orthopedics", 15), ("Emergency", 10),
]
SEED_DOCTORS = [
    ("Dr. Aisha Khan", "General Medicine", "101", 10),
    ("Dr. Rahul Mehta", "General Medicine", "102", 10),
    ("Dr. Sara Lee", "Pediatrics", "201", 12),
    ("Dr. James Okoro", "Cardiology", "301", 15),
    ("Dr. Maria Lopez", "Orthopedics", "401", 15),
]


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0] == 0:
            for name, beds in SEED_DEPARTMENTS:
                conn.execute("INSERT INTO departments (name, total_beds) VALUES (?, ?)", (name, beds))
            for dname, dept, room, avg in SEED_DOCTORS:
                dept_id = conn.execute("SELECT id FROM departments WHERE name=?", (dept,)).fetchone()[0]
                conn.execute("INSERT INTO doctors (name, department_id, room, avg_minutes) VALUES (?,?,?,?)",
                             (dname, dept_id, room, avg))


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- helpers
def staff_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("staff"):
            flash("Please log in as staff.", "error")
            return redirect(url_for("staff_login", next=request.path))
        return f(*a, **kw)
    return wrapper


def get_doctor(doctor_id):
    return get_db().execute("""
        SELECT d.*, dep.name AS department
        FROM doctors d JOIN departments dep ON dep.id = d.department_id
        WHERE d.id = ?""", (doctor_id,)).fetchone()


def queue_for(doctor_id, day=None):
    """All appointments for a doctor on a day, split by status."""
    day = day or date.today().isoformat()
    rows = get_db().execute("""
        SELECT a.*, p.name AS patient_name, p.phone, p.age, p.gender
        FROM appointments a JOIN patients p ON p.id = a.patient_id
        WHERE a.doctor_id = ? AND a.date = ?
        ORDER BY a.token_no""", (doctor_id, day)).fetchall()
    return {
        "all": rows,
        "serving": next((r for r in rows if r["status"] == "in_progress"), None),
        "waiting": [r for r in rows if r["status"] == "waiting"],
        "finished": [r for r in rows if r["status"] in ("done", "cancelled", "no_show")],
    }


def wait_estimate(appt, doctor):
    """Return (people_ahead, estimated_minutes) or None."""
    if appt["status"] != "waiting":
        return None
    q = queue_for(doctor["id"], appt["date"])
    ahead = sum(1 for r in q["waiting"] if r["token_no"] < appt["token_no"])
    if q["serving"]:
        ahead += 1
    return ahead, ahead * doctor["avg_minutes"]


# ---------------------------------------------------------------- public pages
@app.route("/")
def index():
    db = get_db()
    departments = db.execute("SELECT * FROM departments ORDER BY name").fetchall()
    doctors = db.execute("""
        SELECT d.*, dep.name AS department
        FROM doctors d JOIN departments dep ON dep.id = d.department_id
        ORDER BY dep.name, d.name""").fetchall()
    waiting_counts = {d["id"]: len(queue_for(d["id"])["waiting"]) for d in doctors}
    return render_template("index.html", departments=departments, doctors=doctors,
                           waiting_counts=waiting_counts)


@app.route("/book", methods=["GET", "POST"])
def book():
    db = get_db()
    doctors = db.execute("""
        SELECT d.*, dep.name AS department
        FROM doctors d JOIN departments dep ON dep.id = d.department_id
        WHERE d.available = 1 ORDER BY dep.name, d.name""").fetchall()

    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        phone = f.get("phone", "").strip()
        age = f.get("age") or None
        gender = f.get("gender") or None
        doctor_id = f.get("doctor_id")
        appt_date = f.get("date") or date.today().isoformat()
        reason = f.get("reason", "").strip()

        error = None
        if not name or not phone:
            error = "Name and phone number are required."
        elif not doctor_id:
            error = "Please choose a doctor."
        elif appt_date < date.today().isoformat():
            error = "Appointment date cannot be in the past."
        if error:
            flash(error, "error")
            return render_template("book.html", doctors=doctors, form=f, today=date.today().isoformat())

        doctor = get_doctor(doctor_id)
        if not doctor or not doctor["available"]:
            flash("That doctor is not available.", "error")
            return redirect(url_for("book"))

        # reuse patient record if same name + phone
        patient = db.execute("SELECT id FROM patients WHERE phone=? AND lower(name)=lower(?)",
                             (phone, name)).fetchone()
        if patient:
            patient_id = patient["id"]
        else:
            patient_id = db.execute(
                "INSERT INTO patients (name, phone, age, gender, created_at) VALUES (?,?,?,?,?)",
                (name, phone, age, gender, now_str())).lastrowid

        token = db.execute("SELECT COALESCE(MAX(token_no), 0) + 1 FROM appointments "
                           "WHERE doctor_id=? AND date=?", (doctor_id, appt_date)).fetchone()[0]
        appt_id = db.execute("""
            INSERT INTO appointments (patient_id, doctor_id, date, token_no, reason, status, created_at)
            VALUES (?,?,?,?,?,'waiting',?)""",
            (patient_id, doctor_id, appt_date, token, reason, now_str())).lastrowid
        db.commit()
        flash(f"Appointment booked! Your token number is {token}.", "success")
        return redirect(url_for("ticket", appt_id=appt_id))

    return render_template("book.html", doctors=doctors, form={}, today=date.today().isoformat())


@app.route("/ticket/<int:appt_id>")
def ticket(appt_id):
    appt = get_db().execute("""
        SELECT a.*, p.name AS patient_name, p.phone
        FROM appointments a JOIN patients p ON p.id = a.patient_id
        WHERE a.id = ?""", (appt_id,)).fetchone()
    if not appt:
        abort(404)
    doctor = get_doctor(appt["doctor_id"])
    q = queue_for(doctor["id"], appt["date"])
    return render_template("ticket.html", appt=appt, doctor=doctor,
                           estimate=wait_estimate(appt, doctor),
                           now_serving=q["serving"]["token_no"] if q["serving"] else None)


@app.route("/status")
def status():
    phone = request.args.get("phone", "").strip()
    results = []
    if phone:
        rows = get_db().execute("""
            SELECT a.*, p.name AS patient_name, d.name AS doctor_name, dep.name AS department
            FROM appointments a
            JOIN patients p ON p.id = a.patient_id
            JOIN doctors d ON d.id = a.doctor_id
            JOIN departments dep ON dep.id = d.department_id
            WHERE p.phone = ? AND a.date >= ?
            ORDER BY a.date, a.token_no""", (phone, date.today().isoformat())).fetchall()
        for r in rows:
            results.append({"appt": r, "estimate": wait_estimate(r, get_doctor(r["doctor_id"]))})
    return render_template("status.html", phone=phone, results=results)


@app.route("/queue/<int:doctor_id>")
def queue_display(doctor_id):
    doctor = get_doctor(doctor_id)
    if not doctor:
        abort(404)
    return render_template("queue.html", doctor=doctor, q=queue_for(doctor_id))


@app.route("/api/queue/<int:doctor_id>")
def api_queue(doctor_id):
    q = queue_for(doctor_id)
    return jsonify({
        "now_serving": q["serving"]["token_no"] if q["serving"] else None,
        "waiting": [r["token_no"] for r in q["waiting"]],
        "waiting_count": len(q["waiting"]),
    })


# ---------------------------------------------------------------- staff
@app.route("/staff/login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        if request.form.get("password") == STAFF_PASSWORD:
            session["staff"] = True
            return redirect(request.args.get("next") or url_for("staff"))
        flash("Wrong password.", "error")
    return render_template("staff_login.html")


@app.route("/staff/logout")
def staff_logout():
    session.pop("staff", None)
    return redirect(url_for("index"))


@app.route("/staff")
@staff_required
def staff():
    db = get_db()
    departments = db.execute("SELECT * FROM departments ORDER BY name").fetchall()
    doctors = db.execute("""
        SELECT d.*, dep.name AS department
        FROM doctors d JOIN departments dep ON dep.id = d.department_id
        ORDER BY d.available DESC, dep.name, d.name""").fetchall()
    queues = {d["id"]: queue_for(d["id"]) for d in doctors}
    stats = db.execute("""
        SELECT
          SUM(status='waiting')     AS waiting,
          SUM(status='in_progress') AS in_progress,
          SUM(status='done')        AS done,
          COUNT(*)                  AS total
        FROM appointments WHERE date = ?""", (date.today().isoformat(),)).fetchone()
    return render_template("staff.html", departments=departments, doctors=doctors,
                           queues=queues, stats=stats, today=date.today().strftime("%A, %d %B %Y"))


@app.route("/staff/doctor/<int:doctor_id>/next", methods=["POST"])
@staff_required
def call_next(doctor_id):
    db = get_db()
    today = date.today().isoformat()
    # finish whoever is currently being seen
    db.execute("""UPDATE appointments SET status='done', finished_at=?
                  WHERE doctor_id=? AND date=? AND status='in_progress'""",
               (now_str(), doctor_id, today))
    nxt = db.execute("""SELECT id, token_no FROM appointments
                        WHERE doctor_id=? AND date=? AND status='waiting'
                        ORDER BY token_no LIMIT 1""", (doctor_id, today)).fetchone()
    if nxt:
        db.execute("UPDATE appointments SET status='in_progress', called_at=? WHERE id=?",
                   (now_str(), nxt["id"]))
        flash(f"Now calling token {nxt['token_no']}.", "success")
    else:
        flash("No more patients waiting for this doctor.", "info")
    db.commit()
    return redirect(url_for("staff"))


@app.route("/staff/appointment/<int:appt_id>/status", methods=["POST"])
@staff_required
def set_status(appt_id):
    new = request.form.get("status")
    if new not in ("waiting", "in_progress", "done", "cancelled", "no_show"):
        abort(400)
    db = get_db()
    col = "finished_at" if new in ("done", "cancelled", "no_show") else "called_at"
    db.execute(f"UPDATE appointments SET status=?, {col}=? WHERE id=?", (new, now_str(), appt_id))
    db.commit()
    return redirect(url_for("staff"))


@app.route("/staff/doctor/add", methods=["POST"])
@staff_required
def add_doctor():
    f = request.form
    if not f.get("name") or not f.get("department_id"):
        flash("Doctor name and department are required.", "error")
    else:
        get_db().execute(
            "INSERT INTO doctors (name, department_id, room, avg_minutes) VALUES (?,?,?,?)",
            (f["name"].strip(), f["department_id"], f.get("room", "").strip(),
             int(f.get("avg_minutes") or 10)))
        get_db().commit()
        flash("Doctor added.", "success")
    return redirect(url_for("staff"))


@app.route("/staff/doctor/<int:doctor_id>/toggle", methods=["POST"])
@staff_required
def toggle_doctor(doctor_id):
    db = get_db()
    db.execute("UPDATE doctors SET available = 1 - available WHERE id=?", (doctor_id,))
    db.commit()
    return redirect(url_for("staff"))


@app.route("/staff/department/<int:dept_id>/beds", methods=["POST"])
@staff_required
def update_beds(dept_id):
    db = get_db()
    dept = db.execute("SELECT * FROM departments WHERE id=?", (dept_id,)).fetchone()
    if not dept:
        abort(404)
    action = request.form.get("action")
    occ, total = dept["occupied_beds"], dept["total_beds"]
    if action == "admit" and occ < total:
        occ += 1
    elif action == "discharge" and occ > 0:
        occ -= 1
    elif action == "set_total":
        total = max(0, int(request.form.get("total_beds") or 0))
        occ = min(occ, total)
    db.execute("UPDATE departments SET occupied_beds=?, total_beds=? WHERE id=?", (occ, total, dept_id))
    db.commit()
    return redirect(url_for("staff"))


# ---------------------------------------------------------------- run
if __name__ == "__main__":
    init_db()
    app.run(debug=os.environ.get("CAREQUEUE_DEBUG") == "1", host="0.0.0.0", port=5000)
