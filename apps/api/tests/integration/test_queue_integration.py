"""Queue, jobs and no-show sweep on real PostgreSQL: BR-5, BR-6, FR-4.1/4.2/4.4/4.6, FR-5.2, NFR-2, NFR-5, AC-6."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from clinicdesk.modules.booking.sweeps import noshow_sweep
from clinicdesk.modules.jobs import service as jobs

pytestmark = pytest.mark.integration
IST = ZoneInfo("Asia/Kolkata")
MONDAY = date(2026, 11, 23)


def at(hh: int, mm: int = 0, day: int = 0) -> datetime:
    return datetime.combine(MONDAY + timedelta(days=day), time(hh, mm), tzinfo=IST).astimezone(UTC)


async def token(client, fx, patient_idx: int | None = None):
    body = {"doctor_id": fx.doctor_id}
    if patient_idx is not None:
        body["patient_id"] = fx.patient_ids[patient_idx]
    return await client.post("/api/v1/queue/tokens", json=body, headers=fx.h)


async def queue(client, fx):
    r = await client.get("/api/v1/queue", params={"doctor_id": fx.doctor_id, "day": "2026-11-23"}, headers=fx.h)
    assert r.status_code == 200, r.text
    return r.json()[0]


async def test_tokens_numbered_uniquely_and_limited(client, make_clinic, clock):
    """BR-5, FR-4.1: concurrent issues get unique numbers; limit and window enforced."""
    fx = await make_clinic(patients=0)
    sessions = [{"weekday": 0, "start_time": "10:00", "end_time": "13:00", "max_tokens": 3}]
    await client.put(f"/api/v1/doctors/{fx.doctor_id}/sessions", json={"sessions": sessions}, headers=fx.h)

    clock.set(at(8, 59))
    r = await token(client, fx)
    assert r.status_code == 422 and r.json()["error"]["code"] == "token_window_not_open"

    clock.set(at(9, 0))
    results = await asyncio.gather(*(token(client, fx) for _ in range(5)))
    ok = [r.json() for r in results if r.status_code == 201]
    assert sorted(e["token_no"] for e in ok) == [1, 2, 3]
    assert {r.json()["error"]["code"] for r in results if r.status_code != 201} == {"token_limit_reached"}

    clock.set(at(13, 0))
    assert (await token(client, fx)).json()["error"]["code"] in {"session_ended", "no_session"}


async def test_same_patient_double_tap_returns_same_token(client, make_clinic):
    fx = await make_clinic(patients=1)
    a, b = (await token(client, fx, 0)).json(), (await token(client, fx, 0)).json()
    assert a["id"] == b["id"]


async def test_merged_queue_calls_due_booking_then_walkins_and_completes(client, make_clinic, clock, broker):
    """BR-6, FR-4.4, FR-4.6: arrived booked patient whose slot is due goes first; Next completes."""
    fx = await make_clinic(patients=2)
    appt = (
        await client.post(
            "/api/v1/appointments",
            json={
                "doctor_id": fx.doctor_id,
                "patient_id": fx.patient_ids[0],
                "slot_start": at(10, 15).isoformat(),
            },
            headers=fx.h,
        )
    ).json()
    walk = (await token(client, fx, 1)).json()  # token 1, issued 09:00
    clock.set(at(10, 20))
    r = await client.post(f"/api/v1/appointments/{appt['id']}/status", json={"status": "arrived"}, headers=fx.h)
    assert r.status_code == 200, r.text

    q = await queue(client, fx)
    sid = q["id"]
    booked_entry = next(e for e in q["entries"] if e["kind"] == "booked")
    assert booked_entry["token_no"] == 2 and booked_entry["ahead"] == 0

    first = (await client.post(f"/api/v1/queue/sessions/{sid}/next", headers=fx.h)).json()
    assert first["appointment_id"] == appt["id"]
    second = (await client.post(f"/api/v1/queue/sessions/{sid}/next", headers=fx.h)).json()
    assert second["id"] == walk["id"]
    day = (await client.get("/api/v1/appointments", params={"day": "2026-11-23"}, headers=fx.h)).json()
    assert [a["status"] for a in day if a["id"] == appt["id"]] == ["completed"]
    assert (await queue(client, fx))["current_token_no"] == walk["token_no"]

    # NFR-2: a signal (no patient data) went to this clinic's channel only.
    channels = {c for c, _ in broker.published}
    assert channels == {f"clinic:{fx.clinic_id}"}
    assert all("phone" not in m and "name" not in m for _, m in broker.published)


async def test_skip_and_recall(client, make_clinic):
    """FR-4.4: skipped tokens leave the order; recalled ones go next."""
    fx = await make_clinic(patients=2)
    t1, t2 = (await token(client, fx, 0)).json(), (await token(client, fx, 1)).json()
    sid = t1["queue_session_id"]
    assert (await client.post(f"/api/v1/queue/sessions/{sid}/next", headers=fx.h)).json()["id"] == t1["id"]
    assert (await client.post(f"/api/v1/queue/entries/{t1['id']}/skip", headers=fx.h)).json()["status"] == "skipped"
    assert (await client.post(f"/api/v1/queue/sessions/{sid}/next", headers=fx.h)).json()["id"] == t2["id"]
    assert (await client.post(f"/api/v1/queue/entries/{t1['id']}/recall", headers=fx.h)).json()["status"] == "waiting"
    assert (await client.post(f"/api/v1/queue/sessions/{sid}/next", headers=fx.h)).json()["id"] == t1["id"]
    r = await client.post(f"/api/v1/queue/sessions/{sid}/next", headers=fx.h)
    assert r.status_code == 200 and r.json() is None


async def test_public_tracking_has_no_personal_data(client, make_clinic):
    """FR-4.2: token, current token, people ahead, ETA — nothing else."""
    fx = await make_clinic(patients=2)
    await token(client, fx, 0)
    t2 = (await token(client, fx, 1)).json()
    r = await client.get(f"/api/v1/public/queue/{t2['public_code']}")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"token_no", "status", "current_token_no", "ahead", "eta", "doctor_name"}
    assert body["ahead"] == 1 and body["token_no"] == t2["token_no"]
    assert (await client.get("/api/v1/public/queue/" + "x" * 22)).status_code == 404


async def test_queue_cross_tenant_forbidden(client, make_clinic):
    """AC-10 for queue routes."""
    a, b = await make_clinic(patients=0), await make_clinic(patients=0)
    tb = (await token(client, b)).json()
    assert (await client.post(f"/api/v1/queue/sessions/{tb['queue_session_id']}/next", headers=a.h)).status_code == 403
    assert (await client.post(f"/api/v1/queue/entries/{tb['id']}/skip", headers=a.h)).status_code == 403


async def test_noshow_sweep_marks_only_unarrived_after_session_end(client, make_clinic, clock, rt):
    """FR-5.2, AC-6: unmarked → no-show at session end; arrived untouched; idempotent."""
    fx = await make_clinic(patients=2)

    async def book(i, start):
        r = await client.post(
            "/api/v1/appointments",
            json={
                "doctor_id": fx.doctor_id,
                "patient_id": fx.patient_ids[i],
                "slot_start": start.isoformat(),
            },
            headers=fx.h,
        )
        return r.json()

    missed, came = await book(0, at(10)), await book(1, at(10, 30))
    clock.set(at(10, 30))
    await client.post(f"/api/v1/appointments/{came['id']}/status", json={"status": "arrived"}, headers=fx.h)

    clock.set(at(12, 59))
    assert await noshow_sweep(rt) == 0  # session still running
    clock.set(at(13, 0))
    assert await noshow_sweep(rt) >= 1
    assert await noshow_sweep(rt) == 0
    day = {
        a["id"]: a["status"]
        for a in (await client.get("/api/v1/appointments", params={"day": "2026-11-23"}, headers=fx.h)).json()
    }
    assert day[missed["id"]] == "no_show" and day[came["id"]] == "arrived"
    audit = (await client.get("/api/v1/audit", params={"entity_id": missed["id"]}, headers=fx.h)).json()
    assert audit[0]["action"] == "appointment.no_show" and audit[0]["actor_type"] == "system"


async def test_jobs_dedup_claim_once_and_retry(make_clinic, clock, database, rt):
    """NFR-4/5, ADR-0004: dedup on enqueue; concurrent claimers never double-run; failures back off."""
    fx = await make_clinic(patients=0)
    cid = uuid.UUID(fx.clinic_id)
    kind_ok, kind_bad = f"test.ok.{uuid.uuid4().hex[:6]}", f"test.bad.{uuid.uuid4().hex[:6]}"
    ran: list[str] = []

    @jobs.handler(kind_ok)
    async def _ok(jc):
        ran.append(jc.job.dedup_key)

    @jobs.handler(kind_bad)
    async def _bad(jc):
        raise RuntimeError("provider timeout")

    async with database.session(clinic_id=cid) as s:
        keys = [f"{kind_ok}:{i}" for i in range(20)]
        for k in keys:
            assert await jobs.enqueue(s, clinic_id=cid, kind=kind_ok, run_at=clock.now(), dedup_key=k)
        assert not await jobs.enqueue(s, clinic_id=cid, kind=kind_ok, run_at=clock.now(), dedup_key=keys[0])
        await jobs.enqueue(s, clinic_id=cid, kind=kind_bad, run_at=clock.now(), dedup_key=f"{kind_bad}:1")
        await s.commit()

    await asyncio.gather(*(jobs.run_due(rt, limit=7) for _ in range(4)))
    await jobs.run_due(rt)
    assert sorted(k for k in ran if k.startswith(kind_ok)) == sorted(keys)  # each exactly once

    from sqlalchemy import select

    from clinicdesk.modules.jobs.models import ScheduledJob

    async with database.session(bypass_rls=True) as s:
        bad = await s.scalar(select(ScheduledJob).where(ScheduledJob.dedup_key == f"{kind_bad}:1"))
        assert bad.status == "pending" and bad.attempts == 1 and bad.run_at > clock.now()
