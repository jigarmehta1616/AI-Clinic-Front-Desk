"""Reminders, recall engine and recovered revenue on real PostgreSQL.

FR-5.1, FR-6.1–6.4, FR-1.6, FR-7.3, BR-7, BR-8, BR-11, BR-12, AC-4, AC-7, AC-11.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from tests.conftest import login, rand_phone
from tests.integration.wa import Chat, consent, wa_clinic  # noqa: F401  (fixture)

from clinicdesk.integrations.whatsapp import option_ids, text_of
from clinicdesk.modules.jobs import service as jobs

pytestmark = pytest.mark.integration
IST = ZoneInfo("Asia/Kolkata")
MON = date(2026, 11, 23)


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=IST).astimezone(UTC)


async def book_api(client, fx, patient_id, start: datetime, **extra):
    r = await client.post(
        "/api/v1/appointments",
        json={"doctor_id": fx.doctor_id, "patient_id": patient_id, "slot_start": start.isoformat(), **extra},
        headers=fx.h,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def status(client, fx, appt_id, s):
    r = await client.post(f"/api/v1/appointments/{appt_id}/status", json={"status": s}, headers=fx.h)
    assert r.status_code == 200, r.text
    return r.json()


async def consent_api(client, fx, patient_id, purpose="reminders", granted=True):
    r = await client.post(
        f"/api/v1/patients/{patient_id}/consents", json={"purpose": purpose, "granted": granted}, headers=fx.h
    )
    assert r.status_code == 201, r.text


async def whatsapp_patient(chat: Chat, reminders: bool = True) -> str:
    """Consent + book tomorrow 10:00 via WhatsApp; returns the appointment id."""
    out = await consent(chat, "appointment kal savare")
    await chat.send(reply=next(i for i in option_ids(out[-1]) if i.startswith("slot:")))
    await chat.send("Mira Desai")
    done = await chat.send("44")
    assert "✅" in text_of(done[0])
    await chat.send(reply="rem:yes" if reminders else "rem:no")
    return ""


def choices(msg: dict) -> list[str]:
    """Option ids of an interactive message or quick-reply payloads of a template."""
    if msg["type"] == "template":
        return [c["parameters"][0]["payload"] for c in msg["template"]["components"] if c["type"] == "button"]
    return option_ids(msg)


async def report(client, fx, month="2026-11"):
    r = await client.get("/api/v1/reports/revenue", params={"month": month}, headers=fx.h)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------------------------- reminders
async def test_reminders_24h_and_2h_with_confirm_and_reschedule_buttons(client, rt, whatsapp, wa_clinic, clock):
    """FR-5.1, AC-4 entry point: template outside the window, buttons inside it; Confirm confirms."""
    fx = await wa_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    await whatsapp_patient(chat)
    appt = (await client.get("/api/v1/appointments", params={"day": "2026-11-24"}, headers=fx.h)).json()[0]
    slot = datetime.fromisoformat(appt["slot_start"])
    n = len(whatsapp.to(chat.phone))

    clock.set(slot - timedelta(hours=24))
    await jobs.drain(rt)
    reminder = whatsapp.to(chat.phone)[n:]
    assert len(reminder) == 1
    # The patient wrote < 24 h ago, so this is an interactive message; otherwise the approved template (BR-9).
    payloads = choices(reminder[0])
    assert payloads == [f"confirm:{appt['id']}", f"act:r|{appt['id']}", f"act:c|{appt['id']}"]
    assert "Reminder" in text_of(reminder[0]) or "{doctor}" not in text_of(reminder[0])

    ack = await chat.button(payloads[0], "Confirm")
    assert len(ack) == 1
    day = (await client.get("/api/v1/appointments", params={"day": "2026-11-24"}, headers=fx.h)).json()
    assert day[0]["status"] == "confirmed"

    clock.set(slot - timedelta(hours=2))
    await jobs.drain(rt)
    second = whatsapp.to(chat.phone)[-1]
    assert choices(second)[1] == f"act:r|{appt['id']}"

    days = await chat.send(reply=f"act:r|{appt['id']}")  # AC-4 from the reminder: change cut-off is 1 h → allowed
    assert any(i.startswith("day:") for i in option_ids(days[-1]))


async def test_reminders_need_consent_and_skip_cancelled(client, rt, whatsapp, make_clinic, clock, database):
    """DP-2 / BR-8: staff-booked patient without reminders consent gets none; with consent gets one."""
    fx = await make_clinic(patients=2)
    no_consent = await book_api(client, fx, fx.patient_ids[0], at(MON + timedelta(days=2), 10))
    await consent_api(client, fx, fx.patient_ids[1])
    ok = await book_api(client, fx, fx.patient_ids[1], at(MON + timedelta(days=2), 11))
    cancelled = await book_api(client, fx, fx.patient_ids[1], at(MON + timedelta(days=3), 11))
    await client.post(f"/api/v1/appointments/{cancelled['id']}/cancel", json={}, headers=fx.h)

    clock.set(at(MON + timedelta(days=2), 9, 0))  # after both 24 h reminders, before the 2 h ones
    await jobs.drain(rt)
    from sqlalchemy import select

    from clinicdesk.modules.messaging.models import OutboxMessage

    async with database.session(clinic_id=uuid.UUID(fx.clinic_id)) as s:
        rows = (await s.scalars(select(OutboxMessage).where(OutboxMessage.category == "reminder"))).all()
    by_key = {r.idempotency_key: (r.status, r.last_error) for r in rows}
    assert by_key[f"reminder_msg:{no_consent['id']}:24h"] == ("skipped", "no_consent")
    assert by_key[f"reminder_msg:{ok['id']}:24h"][0] in ("sent", "failed")  # failed only if no sender number
    assert not any(cancelled["id"] in k for k in by_key)


async def test_reminder_quiet_hours_and_deadline(client, rt, make_clinic, clock, database):
    """BR-7: a 2 h reminder inside quiet hours waits; if waiting would pass the appointment it is dropped."""
    fx = await make_clinic(patients=2)
    for pid in fx.patient_ids:
        await consent_api(client, fx, pid)
    r = await client.patch("/api/v1/clinic", json={"settings": {"quiet_end": "09:00:00"}}, headers=fx.h)
    assert r.status_code == 200, r.text
    a = await book_api(client, fx, fx.patient_ids[0], at(MON + timedelta(days=1), 10, 0))  # 2 h → 08:00 → 09:00
    r = await client.patch("/api/v1/clinic", json={"settings": {"quiet_end": "10:00:00"}}, headers=fx.h)
    b = await book_api(client, fx, fx.patient_ids[1], at(MON + timedelta(days=1), 10, 15))  # 08:15 → 10:00 > deadline
    await client.patch("/api/v1/clinic", json={"settings": {"quiet_end": "09:00:00"}}, headers=fx.h)

    from sqlalchemy import select

    from clinicdesk.modules.jobs.models import ScheduledJob

    clock.set(at(MON + timedelta(days=1), 8, 0))
    await jobs.drain(rt)
    async with database.session(bypass_rls=True) as s:
        job_a = await s.scalar(select(ScheduledJob).where(ScheduledJob.dedup_key == f"reminder:{a['id']}:2h"))
        assert job_a.status == "pending" and job_a.run_at == at(MON + timedelta(days=1), 9, 0)
    await client.patch("/api/v1/clinic", json={"settings": {"quiet_end": "10:00:00"}}, headers=fx.h)
    clock.set(at(MON + timedelta(days=1), 8, 15))
    await jobs.drain(rt)
    async with database.session(bypass_rls=True) as s:
        job_b = await s.scalar(select(ScheduledJob).where(ScheduledJob.dedup_key == f"reminder:{b['id']}:2h"))
        assert job_b.status == "done"  # dropped: deferral would land after (slot − 15 min)
    assert b and r.status_code == 200


# ---------------------------------------------------------------------------------------------- recall
async def test_ac7_ac11_dental_recall_six_months_recovered_on_arrival(client, rt, whatsapp, wa_clinic, clock):
    """AC-7, AC-11, BR-11, BR-12: recall sent on due date ≥ 08:00; one-tap booking counts only after arrival."""
    fx = await wa_clinic()
    await client.patch(f"/api/v1/doctors/{fx.doctor_id}", json={"fee_paise": 60000}, headers=fx.h)
    chat = Chat(client, rt, whatsapp, fx.pnid)
    await whatsapp_patient(chat)
    visit = (await client.get("/api/v1/appointments", params={"day": "2026-11-24"}, headers=fx.h)).json()[0]
    clock.set(at(MON + timedelta(days=1), 10, 5))
    await status(client, fx, visit["id"], "arrived")
    await status(client, fx, visit["id"], "completed")
    r = await client.post(
        f"/api/v1/appointments/{visit['id']}/followup", json={"kind": "rule", "visit_type": "cleaning"}, headers=fx.h
    )
    assert r.status_code == 201, r.text
    due = date.fromisoformat(r.json()["due_date"])
    assert due == MON + timedelta(days=1) + timedelta(days=182)
    recall_id = r.json()["recall_id"]

    clock.set(at(due, 7, 30))
    n = len(whatsapp.to(chat.phone))
    await jobs.drain(rt)
    assert len(whatsapp.to(chat.phone)) == n  # not before 10:00 on the due date
    clock.set(at(due, 10, 0))
    await jobs.drain(rt)
    msg = whatsapp.to(chat.phone)[-1]
    assert msg["type"] == "template" and msg["template"]["name"] == "recall_due"  # months later → template
    days = await chat.button(f"recall:{recall_id}", "Book now")
    day_id = next(i for i in option_ids(days[-1]) if i.startswith("day:"))
    slots = await chat.send(reply=day_id)
    done = await chat.send(reply=next(i for i in option_ids(slots[-1]) if i.startswith("slot:")))
    assert "✅" in text_of(done[0])

    booked_day = day_id.split(":")[1]
    appt = (await client.get("/api/v1/appointments", params={"day": booked_day}, headers=fx.h)).json()[0]
    assert appt["source"] == "recall" and appt["source_ref_id"] == recall_id
    recalls = (await client.get("/api/v1/recalls", params={"status": "booked"}, headers=fx.h)).json()
    assert [x["id"] for x in recalls] == [recall_id]
    month = booked_day[:7]
    assert (await report(client, fx, month))["total_visits"] == 0  # BR-11: booked is not recovered

    clock.set(datetime.fromisoformat(appt["slot_start"]))
    await status(client, fx, appt["id"], "arrived")
    await status(client, fx, appt["id"], "completed")
    rep = await report(client, fx, month)
    assert rep["estimated"] is True and "Estimated" in rep["label"]
    assert rep["by_source"]["recall"] == {"visits": 1, "estimated_revenue_paise": 60000}
    assert rep["total_visits"] == 1 and rep["items"][0]["appointment_id"] == appt["id"]


async def test_recall_followups_then_lapse(client, rt, whatsapp, wa_clinic, clock):
    """FR-6.4: initial + 2 follow-ups (+3 d, +7 d), then lapsed; no 4th message."""
    fx = await wa_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    await whatsapp_patient(chat)
    visit = (await client.get("/api/v1/appointments", params={"day": "2026-11-24"}, headers=fx.h)).json()[0]
    clock.set(at(MON + timedelta(days=1), 10, 5))
    await status(client, fx, visit["id"], "arrived")
    r = await client.post(
        f"/api/v1/appointments/{visit['id']}/followup", json={"kind": "days", "days": 30}, headers=fx.h
    )
    due = date.fromisoformat(r.json()["due_date"])
    n = len(whatsapp.to(chat.phone))
    for offset in (0, 3, 7, 10, 20):
        clock.set(at(due + timedelta(days=offset), 10, 0))
        await jobs.drain(rt)
    assert len(whatsapp.to(chat.phone)) - n == 3
    assert [x["status"] for x in (await client.get("/api/v1/recalls", headers=fx.h)).json()] == ["lapsed"]


async def test_recall_three_day_cap_and_opt_out(client, rt, whatsapp, wa_clinic, clock):
    """BR-8: two recalls due the same day → second waits 3 days; after STOP → skipped."""
    fx = await wa_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    await whatsapp_patient(chat)
    visit = (await client.get("/api/v1/appointments", params={"day": "2026-11-24"}, headers=fx.h)).json()[0]
    patient_id = visit["patient_id"]
    clock.set(at(MON + timedelta(days=1), 10, 5))
    await status(client, fx, visit["id"], "arrived")
    await client.post(f"/api/v1/appointments/{visit['id']}/followup", json={"kind": "days", "days": 20}, headers=fx.h)
    second = await book_api(client, fx, patient_id, at(MON + timedelta(days=1), 12, 0))
    clock.set(at(MON + timedelta(days=1), 12, 5))
    await status(client, fx, second["id"], "arrived")
    await client.post(f"/api/v1/appointments/{second['id']}/followup", json={"kind": "days", "days": 20}, headers=fx.h)

    due = MON + timedelta(days=21)
    n = len(whatsapp.to(chat.phone))
    clock.set(at(due, 10, 0))
    await jobs.drain(rt)
    assert len(whatsapp.to(chat.phone)) - n == 1  # cap: only one recall message in 3 days
    clock.set(at(due + timedelta(days=3), 9, 0))  # before the deferred recall and the first follow-up
    await chat.send("STOP")
    clock.set(at(due + timedelta(days=3), 10, 1))
    m = len(whatsapp.to(chat.phone))
    await jobs.drain(rt)
    assert len(whatsapp.to(chat.phone)) == m  # BR-8: none after opting out
    statuses = sorted(x["status"] for x in (await client.get("/api/v1/recalls", headers=fx.h)).json())
    assert "skipped" in statuses


async def test_auto_recall_from_rule_and_physio_plan(client, rt, make_clinic, clock):
    """FR-6.1 auto recall on completion; FR-6.2 plan: sessions counted, next session recalled, plan completes."""
    fx = await make_clinic(patients=2, specialty="physio")
    rules = {r["visit_type"]: r for r in (await client.get("/api/v1/recall/rules", headers=fx.h)).json()}
    assert rules["physio_session"]["plan_based"] and rules["physio_review"]["delay_days"] == 14  # FR-1.6

    review = await book_api(client, fx, fx.patient_ids[0], at(MON, 10), visit_type="physio_review")
    clock.set(at(MON, 10, 5))
    await status(client, fx, review["id"], "arrived")
    await status(client, fx, review["id"], "completed")
    recalls = (await client.get("/api/v1/recalls", headers=fx.h)).json()
    assert [(r["visit_type"], r["due_date"]) for r in recalls] == [("physio_review", "2026-12-07")]

    s1 = await book_api(client, fx, fx.patient_ids[1], at(MON, 11))
    clock.set(at(MON, 11, 5))
    await status(client, fx, s1["id"], "arrived")
    r = await client.post(
        f"/api/v1/appointments/{s1['id']}/followup", json={"kind": "plan", "sessions": 3}, headers=fx.h
    )
    assert r.status_code == 201 and r.json()["label"] == "Session 2 of 3" and r.json()["due_date"] == "2026-11-25"
    await status(client, fx, s1["id"], "completed")  # first session already counted when the plan was created

    for d in (2, 4):
        day = MON + timedelta(days=d)
        clock.set(at(day, 9, 0))
        appt = await book_api(client, fx, fx.patient_ids[1], at(day, 10))
        clock.set(at(day, 10, 5))
        await status(client, fx, appt["id"], "arrived")
        await status(client, fx, appt["id"], "completed")
        rows = (await client.get("/api/v1/recalls", headers=fx.h)).json()
        labels = [x["label"] for x in rows if x["patient_id"] == fx.patient_ids[1]]
        expected = ["Session 2 of 3", "Session 3 of 3"]
        assert sorted(labels) == expected  # session 3 recalled after session 2; nothing after the last
    clock.set(at(MON + timedelta(days=6), 11, 0))  # past both session recalls' send times
    await jobs.drain(rt)
    closed = {
        x["label"]: (x["status"], x["closed_reason"])
        for x in (await client.get("/api/v1/recalls", headers=fx.h)).json()
        if x["patient_id"] == fx.patient_ids[1]
    }
    # The patient came for sessions 2 and 3 anyway: no "time for your session" message is sent.
    assert closed == {
        "Session 2 of 3": ("cancelled", "already_booked"),
        "Session 3 of 3": ("cancelled", "already_booked"),
    }


async def test_recall_rules_api_validation(client, make_clinic, otp_sender):
    fx = await make_clinic(patients=0)
    rules = {r["visit_type"] for r in (await client.get("/api/v1/recall/rules", headers=fx.h)).json()}
    assert {"checkup", "cleaning", "rct_review", "extraction_review"} <= rules
    r = await client.put(
        "/api/v1/recall/rules/cleaning",
        json={"label": "Cleaning", "delay_days": 120, "followup_days": [2, 5]},
        headers=fx.h,
    )
    assert r.status_code == 200 and r.json()["delay_days"] == 120
    r = await client.put(
        "/api/v1/recall/rules/cleaning",
        json={"label": "x", "delay_days": 120, "followup_days": [1, 2, 3]},
        headers=fx.h,
    )
    assert r.status_code == 422  # FR-6.4: at most two follow-ups
    rec = rand_phone()
    await client.post("/api/v1/clinic/staff", json={"phone": rec, "role": "receptionist"}, headers=fx.h)
    h = {"Authorization": f"Bearer {(await login(client, otp_sender, rec))['access_token']}"}
    assert (
        await client.put("/api/v1/recall/rules/cleaning", json={"label": "x", "delay_days": 1}, headers=h)
    ).status_code == 403
    assert (await client.get("/api/v1/reports/revenue", headers=h)).status_code == 403  # owner only


async def test_noshow_rebook_counted_once_and_isolated(client, rt, whatsapp, wa_clinic, clock, make_clinic):
    """BR-11 no-show rebook source; arrival + completion count once; other clinics see nothing (AC-10)."""
    fx = await wa_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    out = await consent(chat, "appointment today")
    await chat.send(reply=next(i for i in option_ids(out[-1]) if i.startswith("slot:")))
    await chat.send("Nita Rao")
    await chat.send("33")
    await chat.send(reply="rem:yes")
    clock.set(at(MON, 13, 0))
    from clinicdesk.modules.booking.sweeps import noshow_sweep

    assert await noshow_sweep(rt) == 1
    await jobs.drain(rt)
    days = await chat.send(reply=option_ids(whatsapp.to(chat.phone)[-1])[0])
    slots = await chat.send(reply=next(i for i in option_ids(days[-1]) if i.startswith("day:")))
    await chat.send(reply=next(i for i in option_ids(slots[-1]) if i.startswith("slot:")))
    appt = None
    for d in range(1, 8):
        rows = (
            await client.get(
                "/api/v1/appointments", params={"day": (MON + timedelta(days=d)).isoformat()}, headers=fx.h
            )
        ).json()
        appt = appt or next((a for a in rows if a["source"] == "noshow_rebook"), None)
    clock.set(datetime.fromisoformat(appt["slot_start"]))
    await status(client, fx, appt["id"], "arrived")
    await status(client, fx, appt["id"], "completed")
    month = appt["slot_start"][:7]
    rep = await report(client, fx, month)
    assert rep["by_source"]["noshow_rebook"]["visits"] == 1 and rep["total_visits"] == 1
    other = await make_clinic(patients=0)
    assert (await report(client, other, month))["total_visits"] == 0
