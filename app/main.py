import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db

app = FastAPI(title="Trust-Scored Emergency Mesh")

BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@app.on_event("startup")
def startup():
    db.init_db()
    db.seed_if_empty()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------- Dashboard ----------
@app.get("/api/dashboard")
def dashboard():
    conn = db.get_conn()
    now = datetime.utcnow()
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    total_patients = conn.execute("SELECT COUNT(*) c FROM patients").fetchone()["c"]
    appts_this_week = conn.execute(
        "SELECT COUNT(*) c FROM appointments WHERE scheduled_at >= ?", (week_start.isoformat(),)
    ).fetchone()["c"]
    active_ambulance = conn.execute(
        "SELECT COUNT(*) c FROM ambulance_requests WHERE status IN ('pending','dispatched')"
    ).fetchone()["c"]
    active_blood = conn.execute(
        "SELECT COUNT(*) c FROM blood_reports WHERE expires_at >= ?", (now.isoformat(),)
    ).fetchone()["c"]

    completed = conn.execute(
        "SELECT requested_at, dispatched_at FROM ambulance_requests WHERE dispatched_at IS NOT NULL"
    ).fetchall()
    if completed:
        diffs = []
        for r in completed:
            a = datetime.fromisoformat(r["requested_at"])
            b = datetime.fromisoformat(r["dispatched_at"])
            diffs.append((b - a).total_seconds() / 60.0)
        avg_response = round(sum(diffs) / len(diffs), 1)
    else:
        avg_response = None

    upcoming = conn.execute(
        """SELECT a.id, a.scheduled_at, a.doctor_name, a.reason, p.name as patient_name
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE a.status='scheduled' AND a.scheduled_at BETWEEN ? AND ?
           ORDER BY a.scheduled_at ASC""",
        (now.isoformat(), (now + timedelta(hours=24)).isoformat()),
    ).fetchall()

    conn.close()
    return {
        "total_patients": total_patients,
        "appointments_this_week": appts_this_week,
        "active_ambulance_requests": active_ambulance,
        "active_blood_reports": active_blood,
        "avg_response_minutes": avg_response,
        "due_reminders": [dict(r) for r in upcoming],
    }


# ---------- Patients ----------
@app.get("/api/patients")
def list_patients(q: Optional[str] = None):
    conn = db.get_conn()
    if q:
        rows = conn.execute(
            "SELECT * FROM patients WHERE name LIKE ? OR phone LIKE ? ORDER BY created_at DESC",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM patients ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/patients")
def create_patient(
    name: str = Form(...),
    age: Optional[int] = Form(None),
    gender: Optional[str] = Form(None),
    phone: str = Form(...),
    blood_group: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
):
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO patients (name, age, gender, phone, blood_group, notes, created_at) VALUES (?,?,?,?,?,?,?)",
        (name, age, gender, phone, blood_group, notes, db.now_iso()),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id}


# ---------- Appointments ----------
@app.get("/api/appointments")
def list_appointments(status: Optional[str] = None):
    conn = db.get_conn()
    if status:
        rows = conn.execute(
            """SELECT a.*, p.name as patient_name, p.phone as patient_phone FROM appointments a
               JOIN patients p ON p.id = a.patient_id WHERE a.status = ?
               ORDER BY a.scheduled_at ASC""",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT a.*, p.name as patient_name, p.phone as patient_phone FROM appointments a
               JOIN patients p ON p.id = a.patient_id
               ORDER BY a.scheduled_at ASC"""
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/appointments")
def create_appointment(
    patient_id: int = Form(...),
    doctor_name: str = Form(...),
    scheduled_at: str = Form(...),
    reason: Optional[str] = Form(None),
):
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO appointments (patient_id, doctor_name, scheduled_at, reason, status, created_at) VALUES (?,?,?,?,?,?)",
        (patient_id, doctor_name, scheduled_at, reason, "scheduled", db.now_iso()),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id}


@app.post("/api/appointments/{appt_id}/status")
def update_appointment_status(appt_id: int, status: str = Form(...)):
    valid = {"scheduled", "completed", "no-show", "cancelled"}
    if status not in valid:
        raise HTTPException(400, "invalid status")
    conn = db.get_conn()
    conn.execute("UPDATE appointments SET status = ? WHERE id = ?", (status, appt_id))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------- Ambulance / Trust-Scored Emergency Mesh ----------
def _get_or_create_requester(conn, phone, name):
    row = conn.execute("SELECT * FROM requesters WHERE phone = ?", (phone,)).fetchone()
    if row:
        return row
    cur = conn.execute(
        "INSERT INTO requesters (phone, name, trust_score, verified_requests, flagged_requests, created_at) VALUES (?,?,?,?,?,?)",
        (phone, name, 40, 0, 0, db.now_iso()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM requesters WHERE id = ?", (cur.lastrowid,)).fetchone()


@app.get("/api/ambulances")
def list_ambulances():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM ambulances").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/ambulances/{amb_id}/status")
def set_ambulance_status(amb_id: int, status: str = Form(...)):
    valid = {"available", "busy", "offline"}
    if status not in valid:
        raise HTTPException(400, "invalid status")
    conn = db.get_conn()
    conn.execute("UPDATE ambulances SET status = ? WHERE id = ?", (status, amb_id))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/ambulance-requests")
def create_ambulance_request(
    patient_name: str = Form(...),
    contact_phone: str = Form(...),
    pickup_address: str = Form(...),
    lat: float = Form(...),
    lng: float = Form(...),
    requester_name: Optional[str] = Form(None),
):
    conn = db.get_conn()
    requester = _get_or_create_requester(conn, contact_phone, requester_name or patient_name)
    cur = conn.execute(
        """INSERT INTO ambulance_requests
           (requester_id, patient_name, contact_phone, pickup_address, lat, lng, status, requested_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (requester["id"], patient_name, contact_phone, pickup_address, lat, lng, "pending", db.now_iso()),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id}


@app.get("/api/ambulance-requests")
def list_ambulance_requests(status: Optional[str] = None):
    """
    Returns the live emergency queue ranked by Urgency-Distance Score.
    This is the core novel mechanic: pure logistics urgency (wait time +
    proximity to an available ambulance + requester trust), never medical
    severity — computed fresh on every call so the queue visibly re-sorts.
    """
    conn = db.get_conn()
    q = "SELECT r.*, req.trust_score, req.verified_requests, req.flagged_requests FROM ambulance_requests r JOIN requesters req ON req.id = r.requester_id"
    params = ()
    if status:
        q += " WHERE r.status = ?"
        params = (status,)
    rows = conn.execute(q, params).fetchall()

    results = []
    for r in rows:
        d = dict(r)
        if r["status"] in ("pending",):
            amb, dist = db.nearest_available_ambulance(conn, r["lat"], r["lng"])
            score, breakdown = db.compute_urgency_score(r["requested_at"], dist, r["trust_score"])
            d["urgency_score"] = score
            d["score_breakdown"] = breakdown
            d["nearest_ambulance"] = amb["label"] if amb else None
        else:
            d["urgency_score"] = None
            d["score_breakdown"] = None
            d["nearest_ambulance"] = None
        results.append(d)

    results.sort(key=lambda x: (x["urgency_score"] if x["urgency_score"] is not None else -1), reverse=True)
    conn.close()
    return results


@app.post("/api/ambulance-requests/{req_id}/dispatch")
def dispatch_ambulance(req_id: int):
    conn = db.get_conn()
    r = conn.execute("SELECT * FROM ambulance_requests WHERE id = ?", (req_id,)).fetchone()
    if not r:
        raise HTTPException(404, "not found")
    amb, dist = db.nearest_available_ambulance(conn, r["lat"], r["lng"])
    if not amb:
        raise HTTPException(409, "no ambulance currently available")
    conn.execute(
        "UPDATE ambulance_requests SET status='dispatched', assigned_ambulance_id=?, dispatched_at=? WHERE id=?",
        (amb["id"], db.now_iso(), req_id),
    )
    conn.execute("UPDATE ambulances SET status='busy' WHERE id=?", (amb["id"],))
    conn.commit()
    conn.close()
    return {"ok": True, "assigned_ambulance": amb["label"]}


@app.post("/api/ambulance-requests/{req_id}/complete")
def complete_ambulance_request(req_id: int):
    conn = db.get_conn()
    r = conn.execute("SELECT * FROM ambulance_requests WHERE id = ?", (req_id,)).fetchone()
    if not r:
        raise HTTPException(404, "not found")
    conn.execute(
        "UPDATE ambulance_requests SET status='completed', completed_at=? WHERE id=?",
        (db.now_iso(), req_id),
    )
    if r["assigned_ambulance_id"]:
        conn.execute("UPDATE ambulances SET status='available' WHERE id=?", (r["assigned_ambulance_id"],))
    # reward the requester's trust score for a verified, completed request
    conn.execute(
        "UPDATE requesters SET trust_score = MIN(100, trust_score + 5), verified_requests = verified_requests + 1 WHERE id=?",
        (r["requester_id"],),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/ambulance-requests/{req_id}/flag")
def flag_ambulance_request(req_id: int):
    """Mark a request as spam/false alarm — penalizes requester trust score."""
    conn = db.get_conn()
    r = conn.execute("SELECT * FROM ambulance_requests WHERE id = ?", (req_id,)).fetchone()
    if not r:
        raise HTTPException(404, "not found")
    conn.execute(
        "UPDATE ambulance_requests SET status='cancelled' WHERE id=?", (req_id,)
    )
    conn.execute(
        "UPDATE requesters SET trust_score = MAX(0, trust_score - 20), flagged_requests = flagged_requests + 1 WHERE id=?",
        (r["requester_id"],),
    )
    if r["assigned_ambulance_id"]:
        conn.execute("UPDATE ambulances SET status='available' WHERE id=?", (r["assigned_ambulance_id"],))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------- Blood ----------
@app.get("/api/blood")
def search_blood(blood_group: Optional[str] = None, location: Optional[str] = None, include_expired: bool = False):
    conn = db.get_conn()
    q = "SELECT * FROM blood_reports WHERE 1=1"
    params = []
    if blood_group:
        q += " AND blood_group = ?"
        params.append(blood_group)
    if location:
        q += " AND location_text LIKE ?"
        params.append(f"%{location}%")
    if not include_expired:
        q += " AND expires_at >= ?"
        params.append(datetime.utcnow().isoformat())
    q += " ORDER BY reported_at DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    now = datetime.utcnow()
    out = []
    for r in rows:
        d = dict(r)
        expires = datetime.fromisoformat(r["expires_at"])
        d["minutes_until_expiry"] = round((expires - now).total_seconds() / 60.0, 1)
        out.append(d)
    return out


@app.post("/api/blood")
def report_blood(
    facility_name: str = Form(...),
    blood_group: str = Form(...),
    units: int = Form(...),
    location_text: str = Form(...),
    contact_phone: Optional[str] = Form(None),
    lat: Optional[float] = Form(None),
    lng: Optional[float] = Form(None),
    decay_hours: float = Form(6.0),
):
    conn = db.get_conn()
    now = datetime.utcnow()
    expires = now + timedelta(hours=decay_hours)
    cur = conn.execute(
        """INSERT INTO blood_reports (facility_name, blood_group, units, location_text, lat, lng, reported_at, expires_at, contact_phone)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (facility_name, blood_group, units, location_text, lat, lng, now.isoformat(), expires.isoformat(), contact_phone),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id}


@app.post("/api/blood/{report_id}/reconfirm")
def reconfirm_blood(report_id: int, decay_hours: float = Form(6.0)):
    conn = db.get_conn()
    now = datetime.utcnow()
    expires = now + timedelta(hours=decay_hours)
    conn.execute(
        "UPDATE blood_reports SET reported_at = ?, expires_at = ? WHERE id = ?",
        (now.isoformat(), expires.isoformat(), report_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------- Facilities ----------
@app.get("/api/facilities")
def list_facilities(type: Optional[str] = None):
    conn = db.get_conn()
    if type:
        rows = conn.execute("SELECT * FROM facilities WHERE type = ?", (type,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM facilities").fetchall()
    conn.close()
    return [dict(r) for r in rows]
