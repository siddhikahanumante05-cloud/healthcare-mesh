import sqlite3
import os
import math
from datetime import datetime, timedelta

DB_PATH = os.environ.get("DB_PATH", "/tmp/clinic.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    age INTEGER,
    gender TEXT,
    phone TEXT,
    blood_group TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    doctor_name TEXT,
    scheduled_at TEXT NOT NULL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled',
    created_at TEXT NOT NULL,
    FOREIGN KEY (patient_id) REFERENCES patients(id)
);

CREATE TABLE IF NOT EXISTS requesters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT UNIQUE NOT NULL,
    name TEXT,
    trust_score INTEGER NOT NULL DEFAULT 40,
    verified_requests INTEGER NOT NULL DEFAULT 0,
    flagged_requests INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ambulances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    driver_name TEXT,
    phone TEXT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'available'
);

CREATE TABLE IF NOT EXISTS ambulance_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id INTEGER NOT NULL,
    patient_name TEXT NOT NULL,
    contact_phone TEXT NOT NULL,
    pickup_address TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    assigned_ambulance_id INTEGER,
    requested_at TEXT NOT NULL,
    dispatched_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (requester_id) REFERENCES requesters(id),
    FOREIGN KEY (assigned_ambulance_id) REFERENCES ambulances(id)
);

CREATE TABLE IF NOT EXISTS blood_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    facility_name TEXT NOT NULL,
    blood_group TEXT NOT NULL,
    units INTEGER NOT NULL,
    location_text TEXT NOT NULL,
    lat REAL,
    lng REAL,
    reported_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    contact_phone TEXT
);

CREATE TABLE IF NOT EXISTS facilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    address TEXT NOT NULL,
    lat REAL,
    lng REAL,
    phone TEXT
);
"""


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def nearest_available_ambulance(conn, lat, lng):
    rows = conn.execute("SELECT * FROM ambulances WHERE status = 'available'").fetchall()
    best = None
    best_dist = None
    for r in rows:
        d = haversine_km(lat, lng, r["lat"], r["lng"])
        if best_dist is None or d < best_dist:
            best_dist = d
            best = r
    return best, best_dist


def compute_urgency_score(requested_at_str, distance_km, trust_score):
    """
    Trust-Scored Emergency Mesh core mechanic.
    Never judges medical severity — purely logistics urgency:
      + minutes waited (older requests rise)
      + proximity bonus (closer to an available ambulance = faster to serve)
      + trust bonus (reduces influence of unverified/likely-spam requesters)
    Returns (score, breakdown dict) so the UI can show WHY a request ranks
    where it does — transparency is part of the mechanic.
    """
    requested_at = datetime.fromisoformat(requested_at_str)
    minutes_waited = max(0, (datetime.utcnow() - requested_at).total_seconds() / 60.0)
    wait_component = round(min(minutes_waited * 2, 100), 1)  # cap so a stuck request doesn't break scale

    if distance_km is None:
        proximity_component = 0
    else:
        proximity_component = round(max(0, 40 - distance_km * 2), 1)  # closer = higher, 0 beyond 20km

    trust_component = round((trust_score / 100) * 30, 1)  # trust_score 0-100 -> 0-30 pts

    total = round(wait_component + proximity_component + trust_component, 1)
    return total, {
        "wait_minutes": round(minutes_waited, 1),
        "wait_component": wait_component,
        "distance_km": round(distance_km, 2) if distance_km is not None else None,
        "proximity_component": proximity_component,
        "trust_score": trust_score,
        "trust_component": trust_component,
    }


def now_iso():
    return datetime.utcnow().isoformat()


def seed_if_empty():
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) c FROM patients").fetchone()["c"]
    if count > 0:
        conn.close()
        return
    now = datetime.utcnow()

    patients = [
        ("Anita Deshmukh", 34, "F", "9876500001", "O+", "Regular checkup patient, mild hypertension history noted by GP."),
        ("Ramesh Kulkarni", 58, "M", "9876500002", "B+", "Follow-up for physiotherapy."),
        ("Sneha Joshi", 27, "F", "9876500003", "A-", "First visit, referred by Dr. Patil."),
        ("Vikram Shinde", 45, "M", "9876500004", "AB+", "Diabetic, routine monitoring."),
        ("Priya Rane", 8, "F", "9876500005", "O-", "Pediatric routine vaccination schedule."),
    ]
    pid = {}
    for n, a, g, ph, bg, notes in patients:
        cur = conn.execute(
            "INSERT INTO patients (name, age, gender, phone, blood_group, notes, created_at) VALUES (?,?,?,?,?,?,?)",
            (n, a, g, ph, bg, notes, now.isoformat()),
        )
        pid[n] = cur.lastrowid

    appts = [
        (pid["Anita Deshmukh"], "Dr. Mehta", (now + timedelta(hours=3)).isoformat(), "Routine BP check", "scheduled"),
        (pid["Ramesh Kulkarni"], "Dr. Fernandes", (now + timedelta(hours=26)).isoformat(), "Physio session", "scheduled"),
        (pid["Sneha Joshi"], "Dr. Patil", (now - timedelta(days=1)).isoformat(), "Consultation", "completed"),
        (pid["Vikram Shinde"], "Dr. Mehta", (now + timedelta(hours=1)).isoformat(), "Sugar level review", "scheduled"),
        (pid["Priya Rane"], "Dr. Kadam", (now + timedelta(days=2)).isoformat(), "Vaccination", "scheduled"),
    ]
    for p, doc, when, reason, status in appts:
        conn.execute(
            "INSERT INTO appointments (patient_id, doctor_name, scheduled_at, reason, status, created_at) VALUES (?,?,?,?,?,?)",
            (p, doc, when, reason, status, now.isoformat()),
        )

    requesters = [
        ("9998887771", "Ganesh Pawar", 72, 6, 0),
        ("9998887772", "New Requester", 40, 0, 0),
        ("9998887773", "Meera Iyer", 88, 12, 0),
    ]
    for phone, name, trust, verified, flagged in requesters:
        conn.execute(
            "INSERT INTO requesters (phone, name, trust_score, verified_requests, flagged_requests, created_at) VALUES (?,?,?,?,?,?)",
            (phone, name, trust, verified, flagged, now.isoformat()),
        )

    ambulances = [
        ("PMC-AMB-01", "Suresh Nikam", "9123450001", 18.5204, 73.8567, "available"),
        ("PMC-AMB-02", "Farid Khan", "9123450002", 18.5314, 73.8446, "available"),
        ("PMC-AMB-03", "Baban Gaikwad", "9123450003", 18.5089, 73.8259, "busy"),
        ("PMC-AMB-04", "Rekha Salunkhe", "9123450004", 18.5679, 73.9143, "available"),
    ]
    for label, drv, ph, lat, lng, status in ambulances:
        conn.execute(
            "INSERT INTO ambulances (label, driver_name, phone, lat, lng, status) VALUES (?,?,?,?,?,?)",
            (label, drv, ph, lat, lng, status),
        )

    blood = [
        ("Sahyadri Blood Bank", "O+", 12, "Deccan Gymkhana, Pune", 18.5158, 73.8412, "02023456001"),
        ("Ruby Hall Clinic Blood Center", "A+", 4, "Sassoon Road, Pune", 18.5304, 73.8790, "02023456002"),
        ("Red Cross Pune", "B-", 2, "Camp, Pune", 18.5122, 73.8785, "02023456003"),
        ("Jehangir Hospital Blood Bank", "AB+", 7, "Sassoon Road, Pune", 18.5290, 73.8770, "02023456004"),
        ("KEM Hospital Blood Bank", "O-", 1, "Rasta Peth, Pune", 18.5158, 73.8636, "02023456005"),
    ]
    for name, bg, units, loc, lat, lng, phone in blood:
        reported = now
        expires = now + timedelta(hours=6)
        conn.execute(
            "INSERT INTO blood_reports (facility_name, blood_group, units, location_text, lat, lng, reported_at, expires_at, contact_phone) VALUES (?,?,?,?,?,?,?,?,?)",
            (name, bg, units, loc, lat, lng, reported.isoformat(), expires.isoformat(), phone),
        )

    facilities = [
        ("Sahyadri Super Speciality Hospital", "Hospital", "Karve Road, Pune", 18.5019, 73.8298, "02067213000"),
        ("Ruby Hall Clinic", "Hospital", "Sassoon Road, Pune", 18.5304, 73.8790, "02066455100"),
        ("Sahyadri Blood Bank", "Blood Bank", "Deccan Gymkhana, Pune", 18.5158, 73.8412, "02023456001"),
        ("Pune District General Hospital", "Clinic", "Aundh, Pune", 18.5590, 73.8078, "02025890001"),
    ]
    for name, typ, addr, lat, lng, phone in facilities:
        conn.execute(
            "INSERT INTO facilities (name, type, address, lat, lng, phone) VALUES (?,?,?,?,?,?)",
            (name, typ, addr, lat, lng, phone),
        )

    conn.commit()
    conn.close()
