"""Dashboard read models: FR-7.1 today view, FR-7.2 patient history, staff names; tenant isolation."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

pytestmark = pytest.mark.integration
IST = ZoneInfo("Asia/Kolkata")
MON = date(2026, 11, 23)


def at(hh: int, mm: int = 0) -> str:
    return datetime.combine(MON, time(hh, mm), tzinfo=IST).astimezone(UTC).isoformat()


async def test_today_summary_names_and_history(client, make_clinic, clock):
    fx = await make_clinic(patients=3)
    appts = []
    for i, hh in enumerate((10, 11, 12)):
        r = await client.post(
            "/api/v1/appointments",
            json={"doctor_id": fx.doctor_id, "patient_id": fx.patient_ids[i], "slot_start": at(hh)},
            headers=fx.h,
        )
        appts.append(r.json())
    await client.post(
        "/api/v1/queue/tokens", json={"doctor_id": fx.doctor_id, "patient_id": fx.patient_ids[2]}, headers=fx.h
    )
    clock.set(datetime.fromisoformat(at(10, 5)))
    await client.post(f"/api/v1/appointments/{appts[0]['id']}/status", json={"status": "arrived"}, headers=fx.h)
    await client.post(f"/api/v1/appointments/{appts[2]['id']}/cancel", json={}, headers=fx.h)

    r = await client.get("/api/v1/dashboard/today", params={"day": MON.isoformat()}, headers=fx.h)
    assert r.status_code == 200, r.text
    row = r.json()["doctors"][0]
    assert row["appointments"]["arrived"] == 1 and row["appointments"]["cancelled"] == 1
    assert row["appointments"]["booked"] == 1
    assert row["tokens"]["waiting"] == 2  # walk-in + arrived booked patient
    assert r.json()["open_chats"] == 0

    day = (await client.get("/api/v1/appointments", params={"day": MON.isoformat()}, headers=fx.h)).json()
    assert {a["patient_name"] for a in day} == {"Patient 0", "Patient 1", "Patient 2"}
    q = (
        await client.get("/api/v1/queue", params={"doctor_id": fx.doctor_id, "day": MON.isoformat()}, headers=fx.h)
    ).json()[0]
    assert {e["patient_name"] for e in q["entries"]} == {"Patient 0", "Patient 2"}

    hist = (await client.get(f"/api/v1/patients/{fx.patient_ids[2]}/appointments", headers=fx.h)).json()
    assert [h["status"] for h in hist] == ["cancelled"]

    other = await make_clinic(patients=0)
    assert (await client.get(f"/api/v1/patients/{fx.patient_ids[1]}/appointments", headers=other.h)).status_code == 403
    other_today = (await client.get("/api/v1/dashboard/today", params={"day": MON.isoformat()}, headers=other.h)).json()
    assert other_today["doctors"][0]["appointments"]["arrived"] == 0


async def test_patient_detail_shows_latest_consent(client, make_clinic):
    """DP-2: the profile shows the latest decision per purpose; history stays append-only."""
    fx = await make_clinic(patients=1)
    pid = fx.patient_ids[0]
    url = f"/api/v1/patients/{pid}"
    assert (await client.get(url, headers=fx.h)).json()["reminders_consent"] is None
    await client.post(f"{url}/consents", json={"purpose": "reminders", "granted": True}, headers=fx.h)
    await client.post(f"{url}/consents", json={"purpose": "recalls", "granted": True}, headers=fx.h)
    await client.post(f"{url}/consents", json={"purpose": "recalls", "granted": False}, headers=fx.h)
    body = (await client.get(url, headers=fx.h)).json()
    assert body["reminders_consent"] is True and body["recalls_consent"] is False
