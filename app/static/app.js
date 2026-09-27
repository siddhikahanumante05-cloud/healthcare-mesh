const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));

function toast(msg, ok = true) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `fixed bottom-4 right-4 px-4 py-2 rounded-lg shadow-lg text-sm text-white ${ok ? "bg-emerald-600" : "bg-rose-600"}`;
  setTimeout(() => t.classList.add("hidden"), 2500);
}

function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso + (iso.endsWith("Z") ? "" : "Z"));
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

// ---------------- Tabs ----------------
$$(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    $$(".tab-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    $$(".tab-panel").forEach(p => p.classList.add("hidden"));
    $(`#tab-${btn.dataset.tab}`).classList.remove("hidden");
    loadTab(btn.dataset.tab);
  });
});

function loadTab(tab) {
  if (tab === "dashboard") loadDashboard();
  if (tab === "patients") { loadPatients(); }
  if (tab === "appointments") { loadPatientSelect(); loadAppointments(); }
  if (tab === "ambulance") { loadFleet(); loadQueue(); }
  if (tab === "blood") loadBlood();
  if (tab === "facilities") loadFacilities();
}

setInterval(() => {
  $("#clock").textContent = new Date().toLocaleString();
}, 1000);

// ---------------- Dashboard ----------------
async function loadDashboard() {
  const d = await fetch("/api/dashboard").then(r => r.json());
  const cards = [
    ["Patients", d.total_patients, "bg-blue-50 text-blue-700"],
    ["Appointments (week)", d.appointments_this_week, "bg-indigo-50 text-indigo-700"],
    ["Active Ambulance Reqs", d.active_ambulance_requests, "bg-red-50 text-red-700"],
    ["Active Blood Reports", d.active_blood_reports, "bg-rose-50 text-rose-700"],
    ["Avg Dispatch (min)", d.avg_response_minutes ?? "—", "bg-amber-50 text-amber-700"],
  ];
  $("#stat-cards").innerHTML = cards.map(([label, val, cls]) => `
    <div class="rounded-xl p-4 ${cls}">
      <div class="text-2xl font-bold">${val}</div>
      <div class="text-xs mt-1">${label}</div>
    </div>`).join("");

  const rem = d.due_reminders;
  $("#reminders-list").innerHTML = rem.length
    ? rem.map(r => `
      <div class="flex justify-between items-center border-b border-slate-100 pb-2">
        <div>
          <span class="font-medium">${r.patient_name}</span>
          <span class="text-slate-500"> with ${r.doctor_name} — ${r.reason || ""}</span>
        </div>
        <span class="text-xs text-slate-500">${fmtDate(r.scheduled_at)}</span>
      </div>`).join("")
    : `<p class="text-slate-400 text-sm">No appointments due in the next 24 hours.</p>`;
}

// ---------------- Patients ----------------
async function loadPatients(q = "") {
  const rows = await fetch(`/api/patients${q ? "?q=" + encodeURIComponent(q) : ""}`).then(r => r.json());
  $("#patients-list").innerHTML = rows.length ? rows.map(p => `
    <div class="card flex justify-between items-start">
      <div>
        <div class="font-semibold">${p.name} <span class="text-xs text-slate-400">#${p.id}</span></div>
        <div class="text-xs text-slate-500">${p.age ?? "-"} yrs · ${p.gender ?? "-"} · ${p.phone} · ${p.blood_group ?? "BG unknown"}</div>
        ${p.notes ? `<div class="text-xs text-slate-500 mt-1">${p.notes}</div>` : ""}
      </div>
    </div>`).join("") : `<p class="text-slate-400 text-sm">No patients found.</p>`;
}

$("#patient-search").addEventListener("input", e => loadPatients(e.target.value));

$("#patient-form").addEventListener("submit", async e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const res = await fetch("/api/patients", { method: "POST", body: fd });
  if (res.ok) { toast("Patient registered"); e.target.reset(); loadPatients(); }
  else toast("Failed to register patient", false);
});

// ---------------- Appointments ----------------
async function loadPatientSelect() {
  const rows = await fetch("/api/patients").then(r => r.json());
  const sel = $("#appt-patient-select");
  sel.innerHTML = `<option value="">Select patient</option>` +
    rows.map(p => `<option value="${p.id}">${p.name} (#${p.id})</option>`).join("");
}

async function loadAppointments(status = "") {
  const rows = await fetch(`/api/appointments${status ? "?status=" + status : ""}`).then(r => r.json());
  const statusColor = {
    scheduled: "bg-blue-100 text-blue-700",
    completed: "bg-emerald-100 text-emerald-700",
    "no-show": "bg-amber-100 text-amber-700",
    cancelled: "bg-slate-200 text-slate-600",
  };
  $("#appointments-list").innerHTML = rows.length ? rows.map(a => `
    <div class="card">
      <div class="flex justify-between items-start">
        <div>
          <div class="font-semibold">${a.patient_name} <span class="text-xs text-slate-400">· ${a.patient_phone}</span></div>
          <div class="text-xs text-slate-500">${a.doctor_name} — ${a.reason || "No reason given"}</div>
          <div class="text-xs text-slate-400 mt-1">${fmtDate(a.scheduled_at)}</div>
        </div>
        <span class="badge ${statusColor[a.status] || ""}">${a.status}</span>
      </div>
      ${a.status === "scheduled" ? `
      <div class="flex gap-2 mt-2">
        <button class="btn-sm bg-emerald-600 text-white" onclick="setApptStatus(${a.id},'completed')">Mark completed</button>
        <button class="btn-sm bg-amber-500 text-white" onclick="setApptStatus(${a.id},'no-show')">No-show</button>
        <button class="btn-sm bg-slate-300" onclick="setApptStatus(${a.id},'cancelled')">Cancel</button>
      </div>` : ""}
    </div>`).join("") : `<p class="text-slate-400 text-sm">No appointments.</p>`;
}

async function setApptStatus(id, status) {
  const fd = new FormData(); fd.append("status", status);
  await fetch(`/api/appointments/${id}/status`, { method: "POST", body: fd });
  toast("Appointment updated");
  const active = $("#appt-filters .filter-btn.active");
  loadAppointments(active ? active.dataset.status : "");
}

$$("#appt-filters .filter-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    $$("#appt-filters .filter-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    loadAppointments(btn.dataset.status);
  });
});

$("#appointment-form").addEventListener("submit", async e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const iso = new Date(fd.get("scheduled_at")).toISOString();
  fd.set("scheduled_at", iso);
  const res = await fetch("/api/appointments", { method: "POST", body: fd });
  if (res.ok) { toast("Appointment booked"); e.target.reset(); loadAppointments(); }
  else toast("Failed to book", false);
});

// ---------------- Ambulance / Emergency Mesh ----------------
const PUNE_SAMPLES = [
  { addr: "FC Road, Pune", lat: 18.5236, lng: 73.8478 },
  { addr: "Hadapsar, Pune", lat: 18.5089, lng: 73.9260 },
  { addr: "Baner, Pune", lat: 18.5590, lng: 73.7868 },
  { addr: "Kothrud, Pune", lat: 18.5074, lng: 73.8077 },
];
$("#use-demo-loc").addEventListener("click", () => {
  const s = PUNE_SAMPLES[Math.floor(Math.random() * PUNE_SAMPLES.length)];
  const f = $("#ambulance-form");
  f.pickup_address.value = s.addr;
  f.lat.value = s.lat;
  f.lng.value = s.lng;
});

async function loadFleet() {
  const rows = await fetch("/api/ambulances").then(r => r.json());
  const statusColor = { available: "bg-emerald-100 text-emerald-700", busy: "bg-amber-100 text-amber-700", offline: "bg-slate-200 text-slate-600" };
  $("#ambulance-fleet").innerHTML = rows.map(a => `
    <div class="flex justify-between items-center border-b border-slate-100 pb-1">
      <div>
        <div class="font-medium">${a.label}</div>
        <div class="text-xs text-slate-400">${a.driver_name}</div>
      </div>
      <select class="badge ${statusColor[a.status]} border-0" onchange="setAmbStatus(${a.id}, this.value)">
        <option value="available" ${a.status === "available" ? "selected" : ""}>available</option>
        <option value="busy" ${a.status === "busy" ? "selected" : ""}>busy</option>
        <option value="offline" ${a.status === "offline" ? "selected" : ""}>offline</option>
      </select>
    </div>`).join("");
}

async function setAmbStatus(id, status) {
  const fd = new FormData(); fd.append("status", status);
  await fetch(`/api/ambulances/${id}/status`, { method: "POST", body: fd });
  toast("Ambulance status updated");
  loadFleet(); loadQueue();
}

async function loadQueue() {
  const rows = await fetch("/api/ambulance-requests").then(r => r.json());
  const statusColor = {
    pending: "bg-red-100 text-red-700",
    dispatched: "bg-blue-100 text-blue-700",
    completed: "bg-emerald-100 text-emerald-700",
    cancelled: "bg-slate-200 text-slate-600",
  };
  $("#ambulance-queue").innerHTML = rows.length ? rows.map((r, i) => `
    <div class="card">
      <div class="flex justify-between items-start">
        <div>
          <div class="font-semibold">
            ${r.status === "pending" ? `<span class="text-slate-400">#${i + 1}</span>` : ""}
            ${r.patient_name} <span class="text-xs text-slate-400">· ${r.contact_phone}</span>
          </div>
          <div class="text-xs text-slate-500">${r.pickup_address}</div>
          <div class="text-xs text-slate-400 mt-1">Requested ${fmtDate(r.requested_at)}
            ${r.nearest_ambulance ? ` · nearest: ${r.nearest_ambulance}` : ""}
          </div>
        </div>
        <span class="badge ${statusColor[r.status]}">${r.status}</span>
      </div>
      ${r.urgency_score !== null ? `
      <div class="mt-2">
        <div class="flex justify-between text-xs text-slate-500 mb-1">
          <span>Urgency-Distance Score</span><span class="font-bold text-slate-700">${r.urgency_score}</span>
        </div>
        <div class="score-bar-bg"><div class="score-bar-fill" style="width:${Math.min(100, r.urgency_score)}%"></div></div>
        <div class="text-[11px] text-slate-400 mt-1">
          wait ${r.score_breakdown.wait_minutes}m (+${r.score_breakdown.wait_component})
          · dist ${r.score_breakdown.distance_km ?? "—"}km (+${r.score_breakdown.proximity_component})
          · trust ${r.score_breakdown.trust_score}/100 (+${r.score_breakdown.trust_component})
        </div>
      </div>` : ""}
      ${r.status === "pending" ? `
      <div class="flex gap-2 mt-3">
        <button class="btn-sm bg-slate-900 text-white" onclick="dispatchReq(${r.id})">Dispatch nearest</button>
        <button class="btn-sm bg-rose-100 text-rose-700" onclick="flagReq(${r.id})">Flag as false alarm</button>
      </div>` : ""}
      ${r.status === "dispatched" ? `
      <div class="flex gap-2 mt-3">
        <button class="btn-sm bg-emerald-600 text-white" onclick="completeReq(${r.id})">Mark completed</button>
      </div>` : ""}
    </div>`).join("") : `<p class="text-slate-400 text-sm">No active requests.</p>`;
}

async function dispatchReq(id) {
  const res = await fetch(`/api/ambulance-requests/${id}/dispatch`, { method: "POST" });
  const data = await res.json();
  if (res.ok) toast(`Dispatched ${data.assigned_ambulance}`);
  else toast(data.detail || "No ambulance available", false);
  loadQueue(); loadFleet();
}
async function completeReq(id) {
  await fetch(`/api/ambulance-requests/${id}/complete`, { method: "POST" });
  toast("Request completed — requester trust +5");
  loadQueue(); loadFleet();
}
async function flagReq(id) {
  await fetch(`/api/ambulance-requests/${id}/flag`, { method: "POST" });
  toast("Flagged as false alarm — requester trust -20", false);
  loadQueue(); loadFleet();
}

$("#ambulance-form").addEventListener("submit", async e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const res = await fetch("/api/ambulance-requests", { method: "POST", body: fd });
  if (res.ok) { toast("Request submitted — queue re-ranked"); e.target.reset(); loadQueue(); }
  else toast("Failed to submit", false);
});

setInterval(() => { if (!$("#tab-ambulance").classList.contains("hidden")) loadQueue(); }, 15000);

// ---------------- Blood ----------------
async function loadBlood() {
  const bg = $("#blood-filter-group").value;
  const loc = $("#blood-filter-location").value;
  const params = new URLSearchParams();
  if (bg) params.set("blood_group", bg);
  if (loc) params.set("location", loc);
  const rows = await fetch(`/api/blood?${params}`).then(r => r.json());
  $("#blood-list").innerHTML = rows.length ? rows.map(b => `
    <div class="card">
      <div class="flex justify-between items-start">
        <div>
          <div class="font-semibold">${b.facility_name} <span class="badge bg-rose-100 text-rose-700 ml-1">${b.blood_group}</span></div>
          <div class="text-xs text-slate-500">${b.location_text} · ${b.units} units · ${b.contact_phone || "no contact listed"}</div>
        </div>
        <div class="text-right">
          <div class="text-xs ${b.minutes_until_expiry < 60 ? "text-rose-600 font-semibold" : "text-slate-400"}">
            expires in ${Math.round(b.minutes_until_expiry)}m
          </div>
          <button class="btn-sm bg-slate-900 text-white mt-1" onclick="reconfirm(${b.id})">Re-confirm</button>
        </div>
      </div>
    </div>`).join("") : `<p class="text-slate-400 text-sm">No matching blood availability reports (or all have expired).</p>`;
}

async function reconfirm(id) {
  await fetch(`/api/blood/${id}/reconfirm`, { method: "POST", body: new FormData() });
  toast("Availability re-confirmed, decay timer reset");
  loadBlood();
}

$("#blood-filter-group").addEventListener("change", loadBlood);
$("#blood-filter-location").addEventListener("input", loadBlood);

$("#blood-report-form").addEventListener("submit", async e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const res = await fetch("/api/blood", { method: "POST", body: fd });
  if (res.ok) { toast("Blood availability reported"); e.target.reset(); loadBlood(); }
  else toast("Failed to report", false);
});

// ---------------- Facilities ----------------
async function loadFacilities() {
  const rows = await fetch("/api/facilities").then(r => r.json());
  $("#facilities-list").innerHTML = rows.map(f => `
    <div class="card">
      <div class="font-semibold">${f.name} <span class="badge bg-slate-100 text-slate-600">${f.type}</span></div>
      <div class="text-xs text-slate-500 mt-1">${f.address}</div>
      <div class="text-xs text-slate-400 mt-1">${f.phone || ""}</div>
    </div>`).join("");
}

// initial load
loadDashboard();
