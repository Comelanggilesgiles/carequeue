# CareQueue

Hospital appointment booking, live patient queue and bed availability in one lightweight web app.

## Description

CareQueue helps hospitals reduce crowded waiting rooms. Patients book a doctor and receive a token number straight away, then follow their place in the queue and their estimated waiting time from a phone. Hospital staff use a password-protected dashboard to call patients, manage doctors and update bed occupancy. A full-screen "Now Serving" board can be shown on a waiting-room display.

## Screenshots

> Add your screenshots to a `docs/` folder and replace the placeholders below.

| Home | Ticket | Staff dashboard | Waiting-room board |
|------|--------|-----------------|--------------------|
| `docs/home.png` | `docs/ticket.png` | `docs/staff.png` | `docs/board.png` |

## Key features

- Book an appointment with a doctor and instantly receive a token number
- See how many patients are ahead and the estimated waiting time
- Look up appointments at any time using a phone number
- Live bed availability per department
- Full-screen dark waiting-room board that refreshes automatically
- Staff dashboard: call the next patient, mark done / no-show / cancel
- Add doctors, mark them available or unavailable, update bed counts
- Responsive layout that works on phones, tablets and desktops
- Secrets are read from environment variables, so no password or key is stored in the repository

## Tech stack

- Python 3.9 or newer
- Flask (web framework and Jinja2 templates)
- SQLite (built-in database, no server to install)
- HTML and CSS (no JavaScript framework)

## Install and run (about 5 minutes)

### 1. Get the code

```bash
git clone https://github.com/Comelanggilesgiles/carequeue.git
cd carequeue
```

### 2. Create a virtual environment

Windows (PowerShell):

```powershell
python -m venv venv
venv\Scripts\activate
```

macOS / Linux:

```bash
python3 -m venv venv
source venv/bin/activate
```

If PowerShell blocks the activation script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Start the app

```bash
python app.py
```

Open http://localhost:5000 in your browser. The database and sample departments and doctors are created automatically on first run.

## Usage

1. Open **Book appointment**, enter a name, phone number and doctor, and receive a token.
2. Book a few more patients for the same doctor to build a queue.
3. Open **Staff sign in**, log in, and press **Call next patient**. The patient's ticket page updates to "It is your turn".
4. Click **Open display board** next to a doctor to show the waiting-room screen.
5. In **Bed management**, use **Admit** and **Discharge** and watch the home page change.

To use it from a phone on the same Wi-Fi network, find your computer's IP address (`ipconfig` on Windows) and open `http://YOUR-IP:5000` on the phone.

## Configuration

Settings are read from environment variables. Defaults are for local demo use only.

| Variable | Default | Purpose |
|----------|---------|---------|
| `CAREQUEUE_STAFF_PASSWORD` | `admin123` | Staff sign-in password |
| `CAREQUEUE_SECRET_KEY` | `dev-only-change-me` | Flask session signing key |
| `CAREQUEUE_DEBUG` | off | Set to `1` to enable debug mode (local development only) |

Set them in PowerShell before starting the app:

```powershell
$env:CAREQUEUE_STAFF_PASSWORD = "your-strong-password"
$env:CAREQUEUE_SECRET_KEY = "a-long-random-string"
python app.py
```

## Project structure

```
carequeue/
  app.py              Flask app, routes and database logic
  requirements.txt    Python dependencies
  templates/          HTML templates
  static/style.css    Styles
```

## Security notes

- Change the default staff password and secret key before any real deployment.
- The local database file (`hospital.db`) is excluded from Git because it contains patient data.
- Serve the app over HTTPS and behind a production server (for example Gunicorn) when deploying online.
