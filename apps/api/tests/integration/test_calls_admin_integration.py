"""Missed-call recovery and platform administration on real PostgreSQL.

FR-3.1, FR-3.2, FR-3.4, FR-3.5, AC-3, BR-11 (missed-call source), FR-9.1, FR-9.3, FR-9.4, DP-10.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from tests.conftest import login, rand_phone
from tests.integration.wa import Chat, wa_clinic  # noqa: F401  (fixture)

from clinicdesk.integrations.whatsapp import option_ids, text_of
from clinicdesk.modules.jobs import service as jobs

pytestmark = pytest.mark.integration
IST = ZoneInfo("Asia/Kolkata")
SECRET = "exotel-test-secret-123"


@pytest.fixture
def exotel(app):
    app.state.runtime.settings.exotel_webhook_secret = SECRET
    return app


async def call(
    client, exophone: str, caller: str, *, status: str = "no-answer", sid: str | None = None, secret: str = SECRET
) -> int:
    form = {
        "CallSid": sid or f"sid-{uuid.uuid4().hex}",
        "CallFrom": "0" + caller[-10:],
        "CallTo": "0" + exophone[-10:],
        "DialCallStatus": status,
        "Direction": "incoming",
    }
    r = await client.post(f"/api/v1/webhooks/exotel/{secret}", data=form)
    return r.status_code


@pytest.fixture
def call_clinic(client, wa_clinic, exotel):
    async def _make():
        fx = await wa_clinic()
        fx.exophone = rand_phone()
        r = await client.patch("/api/v1/clinic", json={"exotel_number": fx.exophone}, headers=fx.h)
        assert r.status_code == 200, r.text
        return fx

    return _make


def quick_replies(msg: dict) -> list[str]:
    if msg["type"] == "template":
        return [c["parameters"][0]["payload"] for c in msg["template"]["components"] if c["type"] == "button"]
    return option_ids(msg)


async def test_ac3_missed_call_gets_whatsapp_offer_and_is_listed(client, rt, whatsapp, call_clinic):
    """AC-3, FR-3.1/3.2/3.4: unanswered call → WhatsApp offer (same job run, i.e. well under 60 s) + listed."""
    fx = await call_clinic()
    caller = rand_phone()
    assert await call(client, fx.exophone, caller, secret="wrong") == 404
    assert await call(client, fx.exophone, caller) == 200
    await jobs.drain(rt)
    sent = whatsapp.to(caller)
    assert len(sent) == 1 and sent[0]["type"] == "template" and sent[0]["template"]["name"] == "missed_call_offer"
    rows = (await client.get("/api/v1/missed-calls", headers=fx.h)).json()
    assert len(rows) == 1 and rows[0]["status"] == "pending" and rows[0]["caller_phone"] == caller
    assert rows[0]["offer_sent_at"] == rows[0]["called_at"]
    assert quick_replies(sent[0]) == [f"mc:{rows[0]['id']}", f"mccb:{rows[0]['id']}"]


async def test_duplicates_repeats_and_answered_calls(client, rt, whatsapp, call_clinic, clock):
    """FR-3.5 one message per 30 min; Exotel redelivery deduplicated; answered calls ignored."""
    fx = await call_clinic()
    caller = rand_phone()
    await call(client, fx.exophone, caller, sid="dup-1-" + caller)
    await call(client, fx.exophone, caller, sid="dup-1-" + caller)  # same CallSid redelivered
    clock.set(clock.now() + timedelta(minutes=10))
    await call(client, fx.exophone, caller)  # repeat inside 30 min
    await call(client, fx.exophone, rand_phone(), status="completed")  # answered → ignored
    await jobs.drain(rt)
    rows = (await client.get("/api/v1/missed-calls", headers=fx.h)).json()
    assert [(r["caller_phone"], r["repeat_count"]) for r in rows] == [(caller, 1)]
    assert len(whatsapp.to(caller)) == 1
    clock.set(clock.now() + timedelta(minutes=41))
    await call(client, fx.exophone, caller)  # 41 min after the last call → new missed call
    await jobs.drain(rt)
    assert len((await client.get("/api/v1/missed-calls", headers=fx.h)).json()) == 2
    assert len(whatsapp.to(caller)) == 2


async def test_book_from_offer_recovers_and_counts_on_arrival(client, rt, whatsapp, call_clinic, clock):
    """FR-3.4 recovered, BR-11: counted as missed-call revenue only when the patient arrives."""
    fx = await call_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    await call(client, fx.exophone, chat.phone)
    await jobs.drain(rt)
    call_id = (await client.get("/api/v1/missed-calls", headers=fx.h)).json()[0]["id"]
    out = await chat.button(f"mc:{call_id}", "Book appointment")  # new caller → consent first (DP-1)
    assert option_ids(out[-1]) == ["consent:yes", "consent:no"]
    days = await chat.send(reply="consent:yes")  # the tap is remembered → booking continues
    slots = await chat.send(reply=next(i for i in option_ids(days[-1]) if i.startswith("day:")))
    await chat.send(reply=next(i for i in option_ids(slots[-1]) if i.startswith("slot:")))
    await chat.send("Jayesh Parmar")
    done = await chat.send("47")
    assert "✅" in text_of(done[0])
    row = (await client.get("/api/v1/missed-calls", headers=fx.h)).json()[0]
    assert row["status"] == "recovered" and row["appointment_id"]
    appt_day = None
    for d in range(0, 8):
        day = (date(2026, 11, 23) + timedelta(days=d)).isoformat()
        hit = [
            a
            for a in (await client.get("/api/v1/appointments", params={"day": day}, headers=fx.h)).json()
            if a["id"] == row["appointment_id"]
        ]
        if hit:
            appt_day, appt = day, hit[0]
    assert appt["source"] == "missed_call"
    month = appt_day[:7]
    rep = (await client.get("/api/v1/reports/revenue", params={"month": month}, headers=fx.h)).json()
    assert rep["by_source"]["missed_call"]["visits"] == 0  # booked, not yet arrived
    clock.set(datetime.fromisoformat(appt["slot_start"]))
    await client.post(f"/api/v1/appointments/{appt['id']}/status", json={"status": "arrived"}, headers=fx.h)
    rep = (await client.get("/api/v1/reports/revenue", params={"month": month}, headers=fx.h)).json()
    assert rep["by_source"]["missed_call"]["visits"] == 1


async def test_call_me_back_and_no_reply_follow_up(client, rt, whatsapp, call_clinic, clock):
    """FR-3.4 'call back needed': patient taps Call me back, or does not reply within 15 minutes."""
    fx = await call_clinic()
    a, b = rand_phone(), rand_phone()
    await call(client, fx.exophone, a)
    await call(client, fx.exophone, b)
    await jobs.drain(rt)
    rows = {r["caller_phone"]: r for r in (await client.get("/api/v1/missed-calls", headers=fx.h)).json()}
    chat_a = Chat(client, rt, whatsapp, fx.pnid, a)
    ack = await chat_a.button(f"mccb:{rows[a]['id']}", "Call me back")
    assert len(ack) == 1 and text_of(ack[0]) in {
        "Thanks — the clinic will call you back shortly.",
        "આભાર — ક્લિનિક તમને ટૂંક સમયમાં પાછો ફોન કરશે.",
    }
    clock.set(clock.now() + timedelta(minutes=16))
    await jobs.drain(rt)  # follow-up job: b never replied
    rows = {r["caller_phone"]: r for r in (await client.get("/api/v1/missed-calls", headers=fx.h)).json()}
    assert rows[a]["status"] == "call_back_needed" and rows[b]["status"] == "call_back_needed"
    r = await client.post(
        f"/api/v1/missed-calls/{rows[b]['id']}/resolve", json={"outcome": "called_back"}, headers=fx.h
    )
    assert r.json()["status"] == "resolved"
    today = (await client.get("/api/v1/dashboard/today", params={"day": "2026-11-23"}, headers=fx.h)).json()
    assert today["call_backs_needed"] == 1 and today["missed_calls_today"] == 2


async def test_manual_entry_permissions_and_isolation(client, otp_sender, make_clinic):
    """FRD §9 fallback (manual list), RBAC (doctor 403), tenant isolation (AC-10)."""
    fx = await make_clinic(patients=0)
    other = await make_clinic(patients=0)
    phone = rand_phone()
    r = await client.post("/api/v1/missed-calls", json={"phone": phone}, headers=fx.h)
    assert r.status_code == 201 and r.json()["status"] == "call_back_needed" and r.json()["source"] == "manual"
    assert (await client.post("/api/v1/missed-calls", json={"phone": phone}, headers=fx.h)).status_code == 422
    assert (await client.get("/api/v1/missed-calls", headers=other.h)).json() == []
    assert (
        await client.post(
            f"/api/v1/missed-calls/{r.json()['id']}/resolve", json={"outcome": "not_needed"}, headers=other.h
        )
    ).status_code == 403
    doc = rand_phone()
    await client.post(
        "/api/v1/clinic/staff", json={"phone": doc, "role": "doctor", "doctor_id": fx.doctor_id}, headers=fx.h
    )
    h = {"Authorization": f"Bearer {(await login(client, otp_sender, doc))['access_token']}"}
    assert (await client.get("/api/v1/missed-calls", headers=h)).status_code == 403


# ---------------------------------------------------------------------------------------------- plans & admin
async def test_usage_and_platform_admin_lifecycle(client, otp_sender, make_clinic, database, clock):
    """FR-9.1 usage, FR-9.4 extend / plan / suspend / reactivate; DP-10 no patient data; suspension enforced."""
    fx = await make_clinic(patients=1)
    usage = (await client.get("/api/v1/clinic/usage", headers=fx.h)).json()
    assert usage["plan"] == "pilot" and usage["status"] == "trial" and usage["days_left"] == 90
    assert usage["doctors"] == 1 and usage["doctors_level"] == "ok" and usage["patients"] == 1

    assert (await client.get("/api/v1/admin/clinics", headers=fx.h)).status_code == 403  # owner ≠ platform admin
    admin_phone = rand_phone()
    await login(client, otp_sender, admin_phone)
    async with database.session(bypass_rls=True) as s:
        await s.execute(text("UPDATE users SET is_platform_admin = true WHERE phone = :p"), {"p": admin_phone})
        await s.commit()
    clock.set(clock.now() + timedelta(minutes=11))  # OTP send window
    ah = {"Authorization": f"Bearer {(await login(client, otp_sender, admin_phone))['access_token']}"}

    clinics = (await client.get("/api/v1/admin/clinics", headers=ah)).json()
    mine = next(c for c in clinics if c["id"] == fx.clinic_id)
    assert {"patients", "doctors", "messages_this_month"} <= set(mine)
    assert not any(k in mine for k in ("phone", "patient_names", "messages", "conversations"))  # DP-10

    r = await client.post(f"/api/v1/admin/clinics/{fx.clinic_id}/extend-trial", json={"days": 30}, headers=ah)
    assert r.json()["days_left"] == 120
    r = await client.post(f"/api/v1/admin/clinics/{fx.clinic_id}/plan", json={"plan": "basic"}, headers=ah)
    assert r.json()["plan"] == "basic" and r.json()["status"] == "active"

    r = await client.post(
        f"/api/v1/admin/clinics/{fx.clinic_id}/suspend", json={"reason": "unpaid invoice"}, headers=ah
    )
    assert r.json()["status"] == "suspended"
    blocked = await client.get("/api/v1/appointments", params={"day": "2026-11-23"}, headers=fx.h)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "clinic_suspended"
    assert (await client.get("/api/v1/clinic", headers=fx.h)).status_code == 200  # can still see why
    assert (await client.get("/api/v1/clinic/usage", headers=fx.h)).json()["status"] == "suspended"

    await client.post(f"/api/v1/admin/clinics/{fx.clinic_id}/reactivate", headers=ah)
    assert (await client.get("/api/v1/appointments", params={"day": "2026-11-23"}, headers=fx.h)).status_code == 200
    audit = (await client.get("/api/v1/audit", params={"entity_type": "clinic"}, headers=fx.h)).json()
    assert {"platform.extend_trial", "platform.plan", "platform.suspend", "platform.reactivate"} <= {
        a["action"] for a in audit
    }


_ = (UTC, time)
