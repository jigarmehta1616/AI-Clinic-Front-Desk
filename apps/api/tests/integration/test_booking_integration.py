"""Booking integrity on real PostgreSQL: BR-1..BR-4, BR-13, FR-1.3, FR-2.4, FR-5.2, AC-2, AC-4."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from tests.conftest import MONDAY_0900_IST

pytestmark = pytest.mark.integration
IST = ZoneInfo("Asia/Kolkata")
MONDAY = date(2026, 11, 23)


def slot(day_offset: int, hh: int, mm: int = 0) -> str:
    return datetime.combine(MONDAY + timedelta(days=day_offset), time(hh, mm), tzinfo=IST).astimezone(UTC).isoformat()


async def book(client, fx, patient_idx: int, start: str):
    return await client.post(
        "/api/v1/appointments",
        json={"doctor_id": fx.doctor_id, "patient_id": fx.patient_ids[patient_idx], "slot_start": start},
        headers=fx.h,
    )


async def test_two_patients_same_last_slot_exactly_one_wins(client, make_clinic):
    """BR-1, AC-2: 10 concurrent requests for one slot → one 201, nine 409 slot_taken."""
    fx = await make_clinic(patients=10)
    target = slot(0, 12, 45)  # last slot of the session
    results = await asyncio.gather(*(book(client, fx, i, target) for i in range(10)))
    codes = sorted(r.status_code for r in results)
    assert codes == [201] + [409] * 9, [r.text for r in results if r.status_code not in (201, 409)]
    assert all(r.json()["error"]["code"] == "slot_taken" for r in results if r.status_code == 409)
    # The slot is gone from availability (FR-2.2).
    r = await client.get(
        f"/api/v1/doctors/{fx.doctor_id}/slots",
        params={"from": "2026-11-23", "to": "2026-11-23"},
        headers=fx.h,
    )
    assert datetime.fromisoformat(target) not in [datetime.fromisoformat(s["start"]) for s in r.json()]


async def test_max_two_upcoming_per_phone_per_doctor_under_concurrency(client, make_clinic):
    """BR-4: five concurrent bookings from one number on different slots → exactly two succeed."""
    fx = await make_clinic(patients=1)
    starts = [slot(0, 10, 15 * i) for i in range(4)] + [slot(1, 10)]
    results = await asyncio.gather(*(book(client, fx, 0, s) for s in starts))
    ok = [r for r in results if r.status_code == 201]
    rejected = [r for r in results if r.status_code == 422]
    assert len(ok) == 2 and len(rejected) == 3
    assert {r.json()["error"]["code"] for r in rejected} == {"max_upcoming_reached"}


async def test_horizon_alignment_and_past(client, make_clinic):
    """BR-2 and slot validity."""
    fx = await make_clinic(patients=1)
    assert (await book(client, fx, 0, slot(15, 10))).json()["error"]["code"] == "beyond_horizon"
    assert (await book(client, fx, 0, slot(0, 10, 7))).json()["error"]["code"] == "invalid_slot"
    assert (await book(client, fx, 0, slot(6, 10))).json()["error"]["code"] == "invalid_slot"  # Sunday
    assert (await book(client, fx, 0, slot(-7, 10))).json()["error"]["code"] == "slot_in_past"
    assert (await book(client, fx, 0, slot(14, 10))).status_code == 201  # day 14 allowed


async def test_reschedule_frees_old_slot_and_audits_both(client, make_clinic):
    """FR-2.4, AC-4, BR-13."""
    fx = await make_clinic(patients=2)
    first = (await book(client, fx, 0, slot(1, 10))).json()
    r = await client.post(
        f"/api/v1/appointments/{first['id']}/reschedule", json={"slot_start": slot(1, 11)}, headers=fx.h
    )
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["rescheduled_from_id"] == first["id"]
    # Old slot immediately bookable by someone else.
    assert (await book(client, fx, 1, slot(1, 10))).status_code == 201
    audit = (await client.get("/api/v1/audit", params={"entity_type": "appointment"}, headers=fx.h)).json()
    actions = {(a["action"], a["entity_id"]) for a in audit}
    assert ("appointment.reschedule_from", first["id"]) in actions
    assert ("appointment.reschedule_to", new["id"]) in actions
    assert all(a["actor_type"] == "user" and a["channel"] == "dashboard" for a in audit)


async def test_cancel_cutoff_and_freed_slot(client, make_clinic, clock):
    """BR-3: cancel allowed ≥ 1 h before; refused inside the hour."""
    fx = await make_clinic(patients=2)
    a = (await book(client, fx, 0, slot(0, 11))).json()
    b = (await book(client, fx, 1, slot(0, 12))).json()
    clock.set(MONDAY_0900_IST + timedelta(hours=1, minutes=30))  # 10:30 IST
    r = await client.post(f"/api/v1/appointments/{a['id']}/cancel", json={}, headers=fx.h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "change_cutoff_passed"
    r = await client.post(f"/api/v1/appointments/{b['id']}/cancel", json={"reason": "travel"}, headers=fx.h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert (await book(client, fx, 0, slot(0, 12))).status_code == 201  # freed slot rebookable


async def test_status_lifecycle(client, make_clinic, clock):
    """FR-5.2: arrived only on the day; no-show not before slot; completed after arrived."""
    fx = await make_clinic(patients=2)
    today = (await book(client, fx, 0, slot(0, 10))).json()
    tomorrow = (await book(client, fx, 1, slot(1, 10))).json()

    async def status(appt, s):
        return await client.post(f"/api/v1/appointments/{appt['id']}/status", json={"status": s}, headers=fx.h)

    assert (await status(tomorrow, "arrived")).json()["error"]["code"] == "not_appointment_day"
    assert (await status(today, "no_show")).json()["error"]["code"] == "too_early_for_no_show"
    assert (await status(today, "arrived")).json()["status"] == "arrived"
    assert (await status(today, "cancelled")).status_code == 422  # not an allowed target
    assert (await status(today, "completed")).json()["status"] == "completed"
    assert (await status(today, "arrived")).json()["error"]["code"] == "invalid_transition"
    clock.set(MONDAY_0900_IST + timedelta(days=1, hours=2))
    assert (await status(tomorrow, "no_show")).json()["status"] == "no_show"


async def test_leave_flags_affected_bookings(client, make_clinic):
    """FR-1.3: leave flags upcoming bookings for rescheduling and removes the day's slots."""
    fx = await make_clinic(patients=2)
    a = (await book(client, fx, 0, slot(2, 10))).json()
    b = (await book(client, fx, 1, slot(3, 10))).json()
    r = await client.post(
        "/api/v1/schedule-exceptions",
        json={
            "doctor_id": fx.doctor_id,
            "start_date": "2026-11-25",
            "end_date": "2026-11-25",
            "kind": "leave",
        },
        headers=fx.h,
    )
    assert r.status_code == 201 and r.json()["flagged_appointments"] == 1
    day = (await client.get("/api/v1/appointments", params={"day": "2026-11-25"}, headers=fx.h)).json()
    assert [x["needs_reschedule"] for x in day if x["id"] == a["id"]] == [True]
    other = (await client.get("/api/v1/appointments", params={"day": "2026-11-26"}, headers=fx.h)).json()
    assert [x["needs_reschedule"] for x in other if x["id"] == b["id"]] == [False]
    r = await client.get(
        f"/api/v1/doctors/{fx.doctor_id}/slots",
        params={"from": "2026-11-25", "to": "2026-11-25"},
        headers=fx.h,
    )
    assert r.json() == []


async def test_slots_endpoint_offers_next_free(client, make_clinic):
    """FR-2.2: future, free, aligned slots in order (limit honoured)."""
    fx = await make_clinic(patients=1)
    await book(client, fx, 0, slot(0, 10))
    r = await client.get(
        f"/api/v1/doctors/{fx.doctor_id}/slots",
        params={"from": "2026-11-23", "to": "2026-11-23", "limit": 3},
        headers=fx.h,
    )
    got = [datetime.fromisoformat(s["start"]) for s in r.json()]
    assert got == [datetime.fromisoformat(slot(0, 10, m)) for m in (15, 30, 45)]
