"""Auth, RBAC and tenant isolation on real PostgreSQL: NFR-10, DP-6, DP-10, AC-10, BR-13."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.conftest import login, rand_phone

pytestmark = pytest.mark.integration


async def test_signup_onboarding_and_me(client, otp_sender):
    """FR-1.1: OTP sign-up → user without clinic → create clinic → owner token."""
    phone = rand_phone()
    tokens = await login(client, otp_sender, phone)
    assert tokens["clinic_id"] is None and tokens["memberships"] == []
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert (await client.get("/api/v1/clinic", headers=h)).json()["error"]["code"] == "no_clinic_selected"
    r = await client.post(
        "/api/v1/clinics",
        json={"name": "Physio Plus", "slug": "PHY" + uuid.uuid4().hex[:6].upper(), "specialty": "physio"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    owner = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    me = (await client.get("/api/v1/auth/me", headers=owner)).json()
    assert me["role"] == "owner" and me["phone"] == phone and len(me["memberships"]) == 1
    clinic = (await client.get("/api/v1/clinic", headers=owner)).json()
    assert clinic["settings"]["booking_horizon_days"] == 14 and clinic["trial_ends_at"]


async def test_otp_wrong_code_lockout_and_rate_limit(client, otp_sender):
    """NFR-10: 5 attempts per challenge; 3 sends per 10 minutes."""
    phone = rand_phone()
    await client.post("/api/v1/auth/otp/request", json={"phone": phone})
    good = otp_sender.codes[phone]
    bad = "000000" if good != "000000" else "111111"
    for _ in range(5):
        r = await client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": bad})
        assert r.status_code == 401
    r = await client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": good})
    assert r.status_code == 401, "challenge must be locked after 5 failures"
    assert (await client.post("/api/v1/auth/otp/request", json={"phone": phone})).status_code == 202
    assert (await client.post("/api/v1/auth/otp/request", json={"phone": phone})).status_code == 202
    r = await client.post("/api/v1/auth/otp/request", json={"phone": phone})
    assert r.status_code == 429 and r.json()["error"]["code"] == "otp_rate_limited"


async def _refresh(client, token: str):
    client.cookies.clear()
    client.cookies.set("cd_refresh", token)
    r = await client.post("/api/v1/auth/refresh")
    return r, r.cookies.get("cd_refresh")


async def test_refresh_reuse_within_grace_is_a_benign_race(client, otp_sender, clock):
    """ADR-0007: a reload mid-refresh replays the spent token within seconds → new token, session kept."""
    await login(client, otp_sender, rand_phone())
    first = client.cookies.get("cd_refresh")
    r, second = await _refresh(client, first)
    assert r.status_code == 200 and second and second != first
    clock.set(clock.now() + timedelta(seconds=10))
    r, third = await _refresh(client, first)  # replay of the spent token inside the window
    assert r.status_code == 200, r.text
    assert third not in (first, second)
    r, _ = await _refresh(client, second)
    assert r.status_code == 200  # the family is still valid


async def test_refresh_rotation_and_reuse_detection(client, otp_sender, clock):
    """NFR-10, ADR-0007: rotate on use; replaying a spent token after the grace window revokes the family."""
    await login(client, otp_sender, rand_phone())
    first = client.cookies.get("cd_refresh")
    r, second = await _refresh(client, first)
    assert r.status_code == 200 and second and second != first
    clock.set(clock.now() + timedelta(seconds=31))
    r, _ = await _refresh(client, first)
    assert r.status_code == 401 and r.json()["error"]["code"] == "refresh_reused"
    r, _ = await _refresh(client, second)
    assert r.status_code == 401, "family must be revoked after reuse"


async def test_cross_tenant_patient_access_is_403_and_logged(client, make_clinic):
    """AC-10, DP-6: Clinic A staff requesting Clinic B's patient → 403, audit row in A."""
    a = await make_clinic(patients=1)
    b = await make_clinic(patients=1)
    target = b.patient_ids[0]
    r = await client.get(f"/api/v1/patients/{target}", headers=a.h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_or_not_found"
    audit = (await client.get("/api/v1/audit", params={"entity_id": target}, headers=a.h)).json()
    assert [x["action"] for x in audit] == ["access_denied"]
    # Same for mutation endpoints on another clinic's appointment id and for booking B's patient.
    r = await client.post(f"/api/v1/appointments/{uuid.uuid4()}/cancel", json={}, headers=a.h)
    assert r.status_code == 403
    r = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": b.doctor_id,
            "patient_id": b.patient_ids[0],
            "slot_start": "2026-11-24T04:30:00+00:00",
        },
        headers=a.h,
    )
    assert r.status_code == 403
    listing = (await client.get("/api/v1/patients", headers=a.h)).json()
    assert {p["id"] for p in listing} == set(a.patient_ids)


async def test_rls_blocks_unscoped_queries(database, make_clinic):
    """ADR-0002: even a query with no WHERE clause sees only the session's tenant."""
    a = await make_clinic(patients=2)
    b = await make_clinic(patients=3)
    async with database.session(clinic_id=uuid.UUID(a.clinic_id)) as s:
        ids = {str(x) for x in (await s.scalars(text("SELECT id FROM patients"))).all()}
    assert ids == set(a.patient_ids)
    async with database.session() as s:  # no tenant context at all
        assert (await s.scalar(text("SELECT count(*) FROM patients"))) == 0
        assert (await s.scalar(text("SELECT count(*) FROM appointments"))) == 0
    async with database.session(clinic_id=uuid.UUID(a.clinic_id)) as s:
        with pytest.raises(DBAPIError):  # WITH CHECK: cannot write into another tenant
            await s.execute(
                text("INSERT INTO patients (clinic_id, phone, name) VALUES (:c, '+919999999999', 'x')"),
                {"c": b.clinic_id},
            )


async def test_audit_log_is_append_only_for_runtime_role(database, make_clinic):
    """BR-13: the app role cannot update or delete audit rows."""
    a = await make_clinic(patients=0)
    async with database.session(clinic_id=uuid.UUID(a.clinic_id)) as s:
        with pytest.raises(DBAPIError, match="permission denied"):
            await s.execute(text("UPDATE audit_log SET action = 'x'"))
    async with database.session(clinic_id=uuid.UUID(a.clinic_id)) as s:
        with pytest.raises(DBAPIError, match="permission denied"):
            await s.execute(text("DELETE FROM audit_log"))


async def test_rbac_receptionist_and_doctor(client, otp_sender, make_clinic):
    """FRD §3: receptionist books but cannot change clinic settings; doctor cannot book."""
    fx = await make_clinic(patients=1)
    rec_phone, doc_phone = rand_phone(), rand_phone()
    r = await client.post("/api/v1/clinic/staff", json={"phone": rec_phone, "role": "receptionist"}, headers=fx.h)
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/v1/clinic/staff",
        json={"phone": doc_phone, "role": "doctor", "doctor_id": fx.doctor_id},
        headers=fx.h,
    )
    assert r.status_code == 201, r.text

    rec = {"Authorization": f"Bearer {(await login(client, otp_sender, rec_phone))['access_token']}"}
    doc = {"Authorization": f"Bearer {(await login(client, otp_sender, doc_phone))['access_token']}"}

    r = await client.patch("/api/v1/clinic", json={"settings": {"booking_horizon_days": 30}}, headers=rec)
    assert r.status_code == 403 and r.json()["error"]["code"] == "permission_denied"
    r = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": fx.doctor_id,
            "patient_id": fx.patient_ids[0],
            "slot_start": "2026-11-24T04:30:00+00:00",
        },
        headers=rec,
    )
    assert r.status_code == 201, r.text
    appt = r.json()
    r = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": fx.doctor_id,
            "patient_id": fx.patient_ids[0],
            "slot_start": "2026-11-24T04:45:00+00:00",
        },
        headers=doc,
    )
    assert r.status_code == 403
    assert (
        await client.post("/api/v1/clinic/staff", json={"phone": rand_phone(), "role": "owner"}, headers=doc)
    ).status_code == 403
    # Doctor can see own schedule.
    day = (await client.get("/api/v1/appointments", params={"day": "2026-11-24"}, headers=doc)).json()
    assert [x["id"] for x in day] == [appt["id"]]
    # Invited memberships became active on first login.
    staff = (await client.get("/api/v1/clinic/staff", headers=fx.h)).json()
    assert {s["status"] for s in staff} == {"active"}
