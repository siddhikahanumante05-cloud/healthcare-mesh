# Trust-Scored Emergency Mesh

Healthcare coordination MVP for small clinics — patient records, appointments,
ambulance dispatch, and blood-availability search — with one novel mechanic:
a live **Urgency-Distance Score** that ranks the emergency queue by pure
logistics urgency (never medical severity), and **Availability Decay** that
auto-expires stale blood-stock reports.

Administrative/coordination only — no diagnosis or treatment logic anywhere
in the system.

## What's novel

1. **Urgency-Distance Score** (ambulance queue): every pending request is
   ranked live by `minutes waited + proximity to nearest available ambulance
   + requester trust score`. The score and its breakdown are shown in the
   UI so staff can see *why* a request is ranked where it is — this sidesteps
   medical triage entirely while still being smarter than first-come-first-served.
2. **Trust Score**: requesters build trust with verified completed requests
   (+5) and lose it when flagged as a false alarm (-20) — a lightweight
   spam/prank defense manual systems (phone/WhatsApp) have no way to apply.
3. **Availability Decay**: blood-stock reports auto-expire 6 hours after
   being reported unless a facility re-confirms, so search results never
   show stale "yes we have it" data — a real failure mode of static PDF/
   WhatsApp blood-bank directories.

## Local run

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
# open http://localhost:8080
```

The SQLite DB is seeded automatically on first run with demo patients,
ambulances, blood reports, and facilities.

## Deploy to Google Cloud Run

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

gcloud run deploy healthcare-mesh \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --port 8080
```

Cloud Run builds the container from the Dockerfile automatically and prints
a public `*.run.app` URL when done — that's your submission link. Open it in
an incognito tab to confirm the jury can reach it without your login.

Note: SQLite here is file-based (`/tmp/clinic.db`), which is fine for a
single-instance demo but resets on cold start/redeploy. For anything beyond
the hackathon, swap `DB_PATH` to a Cloud SQL/Postgres connection.

## 90-second demo script

1. **Dashboard** (10s) — show live stats: patients, appointments this week,
   active ambulance requests, active blood reports.
2. **Emergency Mesh tab** (40s) — the centerpiece:
   - Submit two ambulance requests from different Pune locations (use the
     "use a sample Pune location" button) with different requester phone
     numbers.
   - Point out the queue re-sorts live by **Urgency-Distance Score**, and
     expand the breakdown line (wait / distance / trust) showing *why*.
   - Click **Dispatch nearest** — show the assigned ambulance flips to
     "busy" in the fleet panel.
   - Click **Flag as false alarm** on a request to show the trust-penalty
     mechanic working.
3. **Blood Availability tab** (25s) — show a report, point out the
   "expires in Xm" countdown, then click **Re-confirm** to reset the decay
   timer — explain this is what keeps the directory trustworthy vs. a
   static PDF/WhatsApp list.
4. **Appointments tab** (15s) — book one appointment, mark another
   "completed" to show status flow, point to the Dashboard's follow-up
   reminders panel picking it up.

## Project structure

```
healthcare-mesh/
├── app/
│   ├── main.py          # FastAPI routes (all API + page serving)
│   ├── db.py             # schema, seed data, scoring logic
│   ├── templates/index.html
│   └── static/{app.js,style.css}
├── Dockerfile
├── requirements.txt
└── README.md
```
