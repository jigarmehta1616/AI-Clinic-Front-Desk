"""Seed a demo clinic through the real API (dev only). Safe to re-run: it reuses the demo owner's clinic.

Usage:  python scripts/seed_demo.py http://127.0.0.1:8000 .tmp/server.log
Sign in afterwards on the dashboard with +91 90000 00001 (the OTP is printed in the server log).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

BASE, LOG = sys.argv[1], Path(sys.argv[2])
OWNER = "+919000000001"
IST = ZoneInfo("Asia/Kolkata")
ENV = dict(
    line.split("=", 1) for line in Path(".env").read_text(encoding="utf8").splitlines() if "=" in line and line[0] != "#"
)
SECRET = ENV.get("WHATSAPP_APP_SECRET", "").split("#")[0].strip()
PATIENTS = [
    ("Kantaben Patel", 64, "gu"), ("Ramesh Shah", 51, "gu"), ("Asha Mehta", 35, "hi"), ("Nita Rao", 33, "en"),
    ("Bhavna Joshi", 29, "gu"), ("Harsh Desai", 42, "gu"), ("Meera Iyer", 38, "en"), ("Vikram Solanki", 57, "hi"),
]


def otp() -> str:
    time.sleep(0.4)
    return re.findall(r'"code":\s*"(\d{6})"', LOG.read_text(encoding="utf8", errors="ignore"))[-1]


def main() -> None:
    c = httpx.Client(base_url=f"{BASE}/api/v1", timeout=15)
    c.post("/auth/otp/request", json={"phone": OWNER}).raise_for_status()
    tok = c.post("/auth/otp/verify", json={"phone": OWNER, "code": otp()}).json()
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    if not tok["clinic_id"]:
        r = c.post("/clinics", headers=h, json={
            "name": "Smile Dental Studio", "slug": "SMILE" + uuid.uuid4().hex[:4].upper(), "specialty": "dental",
            "address": "2nd floor, Shivalik Plaza, CG Road, Ahmedabad", "map_url": "https://maps.google.com/?q=CG+Road+Ahmedabad",
            "phone": "+919000000002", "default_fee_paise": 50000})
        r.raise_for_status()
        h = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    pnid = str(uuid.uuid4().int)[:15]
    c.patch("/clinic", headers=h, json={"wa_phone_number_id": pnid, "phone": "+919000000002"}).raise_for_status()

    doctors = c.get("/doctors", headers=h).json()
    if not doctors:
        for name, fee in (("Dr. Mehul Shah", 60000), ("Dr. Priya Patel", None)):
            d = c.post("/doctors", headers=h, json={"name": name, "fee_paise": fee, "slot_minutes": 15}).json()
            sessions = [{"weekday": w, "start_time": "08:00", "end_time": "21:00", "max_tokens": 40} for w in range(7)]
            c.put(f"/doctors/{d['id']}/sessions", headers=h, json={"sessions": sessions}).raise_for_status()
        doctors = c.get("/doctors", headers=h).json()

    existing = {p["name"]: p for p in c.get("/patients", headers=h, params={"limit": 200}).json()}
    people = []
    for i, (name, age, lang) in enumerate(PATIENTS):
        p = existing.get(name) or c.post("/patients", headers=h, json={
            "name": name, "age": age, "language": lang, "phone": f"+9198250{10000 + i:05d}"}).json()
        people.append(p)
        c.post(f"/patients/{p['id']}/consents", headers=h, json={"purpose": "reminders", "granted": True})

    today = datetime.now(IST).date().isoformat()
    booked = 0
    for doc in doctors:
        slots = c.get(f"/doctors/{doc['id']}/slots", headers=h, params={"from": today, "to": today, "limit": 12}).json()
        for p, s in zip(people[:6] if doc is doctors[0] else people[6:], slots[::2], strict=False):
            r = c.post("/appointments", headers=h, json={"doctor_id": doc["id"], "patient_id": p["id"],
                                                         "slot_start": s["start"], "source": "staff"})
            booked += r.status_code == 201
    appts = c.get("/appointments", headers=h, params={"day": today}).json()
    for a in appts[:2]:
        c.post(f"/appointments/{a['id']}/status", headers=h, json={"status": "arrived"})
    for p in people[5:8]:
        c.post("/queue/tokens", headers=h, json={"doctor_id": doctors[0]["id"], "patient_id": p["id"]})

    if SECRET:  # an emergency and a medical question arriving over WhatsApp (dev log provider: nothing is sent)
        for phone, text in (("919825099001", "chest pain since morning, what to do"), ("919825099002", "which medicine for tooth pain?")):
            body = json.dumps({"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": pnid}, "messages": [
                {"from": phone, "id": f"wamid.seed.{uuid.uuid4().hex}", "type": "text", "text": {"body": text}}]}}]}]})
            sig = "sha256=" + hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
            c.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sig, "content-type": "application/json"})
    print(f"seeded: {len(doctors)} doctors, {len(people)} patients, {booked} new bookings today, tokens + inbox chats")
    print(f"sign in at the dashboard with {OWNER}")


if __name__ == "__main__":
    main()
    _ = timedelta
