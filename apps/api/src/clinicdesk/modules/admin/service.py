"""Pilot plan usage (FR-9.1, FR-9.3) and platform administration (FR-9.4).

Platform admins see clinic-level counts only. They have no endpoint that returns patients or conversations
(DP-10: reading conversations needs a clinic support ticket — not built in v1, so it is simply impossible).
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core.context import RequestContext
from clinicdesk.core.db import Database
from clinicdesk.core.errors import NotFound, PolicyViolation
from clinicdesk.modules.audit import service as audit
from clinicdesk.modules.calls import policy
from clinicdesk.modules.messaging.models import OutboxMessage
from clinicdesk.modules.patients.models import Patient
from clinicdesk.modules.scheduling.models import Doctor
from clinicdesk.modules.tenancy.models import Clinic


def month_start(now: datetime, tz: ZoneInfo) -> datetime:
    local = now.astimezone(tz)
    return datetime(local.year, local.month, 1, tzinfo=tz).astimezone(UTC)


async def _counts(s: AsyncSession, clinic: Clinic, now: datetime) -> dict[str, int]:
    since = month_start(now, ZoneInfo(clinic.timezone))
    messages = await s.scalar(
        select(func.count()).where(
            OutboxMessage.clinic_id == clinic.id, OutboxMessage.status == "sent", OutboxMessage.sent_at >= since
        )
    )
    doctors = await s.scalar(select(func.count()).where(Doctor.clinic_id == clinic.id, Doctor.is_active.is_(True)))
    patients = await s.scalar(select(func.count()).where(Patient.clinic_id == clinic.id))
    return {"messages_this_month": int(messages or 0), "doctors": int(doctors or 0), "patients": int(patients or 0)}


def _usage(clinic: Clinic, counts: dict[str, int], now: datetime) -> dict[str, Any]:
    limits = policy.PLANS.get(clinic.plan, policy.PLANS["pilot"])
    return {
        "plan": clinic.plan,
        "status": clinic.status,
        "trial_ends_at": clinic.trial_ends_at,
        "days_left": policy.days_left(clinic.trial_ends_at, now) if clinic.status == "trial" else None,
        "messages_this_month": counts["messages_this_month"],
        "messages_limit": limits["messages_per_month"],
        "messages_level": policy.usage_level(counts["messages_this_month"], limits["messages_per_month"]),
        "doctors": counts["doctors"],
        "doctors_limit": limits["doctors"],
        "doctors_level": policy.usage_level(counts["doctors"], limits["doctors"]),
        "patients": counts["patients"],
    }


async def usage(s: AsyncSession, ctx: RequestContext, now: datetime) -> dict[str, Any]:
    """FR-9.1: the owner sees days left and usage; FR-9.3 levels warn at 80 % and 100 %."""
    clinic = await s.get(Clinic, ctx.tenant)
    assert clinic is not None
    return _usage(clinic, await _counts(s, clinic, now), now)


# ------------------------------------------------------------------ suspension check (per request, cached)
_STATUS_TTL_S = 30.0
_status_cache: dict[uuid.UUID, tuple[str, float]] = {}


async def clinic_status(db: Database, clinic_id: uuid.UUID) -> str:
    """Suspensions take effect within 30 s on every API process (small TTL cache, one PK lookup otherwise)."""
    hit = _status_cache.get(clinic_id)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    async with db.session(clinic_id=clinic_id) as s:
        status = await s.scalar(select(Clinic.status).where(Clinic.id == clinic_id)) or "suspended"
    _status_cache[clinic_id] = (status, time.monotonic() + _STATUS_TTL_S)
    return status


def forget_status(clinic_id: uuid.UUID) -> None:
    _status_cache.pop(clinic_id, None)


# ------------------------------------------------------------------ platform admin (FR-9.4)
async def list_clinics(db: Database, now: datetime) -> list[dict[str, Any]]:
    async with db.session(bypass_rls=True) as s:  # audited platform path; counts only, no patient data
        clinics = (await s.scalars(select(Clinic).order_by(Clinic.created_at.desc()))).all()
        out = []
        for c in clinics:
            counts = await _counts(s, c, now)
            out.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "slug": c.slug,
                    "specialty": c.specialty,
                    "created_at": c.created_at,
                    **_usage(c, counts, now),
                }
            )
        return out


async def change_clinic(
    db: Database, ctx: RequestContext, clinic_id: uuid.UUID, now: datetime, *, action: str, value: Any = None
) -> dict[str, Any]:
    async with db.session(bypass_rls=True) as s:
        clinic = await s.scalar(select(Clinic).where(Clinic.id == clinic_id).with_for_update())
        if clinic is None:
            raise NotFound("clinic not found")
        before = {"status": clinic.status, "plan": clinic.plan, "trial_ends_at": clinic.trial_ends_at}
        if action == "extend_trial":
            base = max(clinic.trial_ends_at or now, now)
            clinic.trial_ends_at = base + timedelta(days=int(value))
            if clinic.status != "suspended":
                clinic.status = "trial"
        elif action == "plan":
            clinic.plan = str(value)
            if clinic.status == "trial":
                clinic.status = "active"
        elif action == "suspend":
            clinic.status = "suspended"
        elif action == "reactivate":
            if clinic.status != "suspended":
                raise PolicyViolation("clinic is not suspended", code="not_suspended")
            clinic.status = "trial" if clinic.trial_ends_at and clinic.trial_ends_at > now else "active"
        audit.record(
            s,
            ctx,
            f"platform.{action}",
            "clinic",
            clinic.id,
            before=before,
            after={
                "status": clinic.status,
                "plan": clinic.plan,
                "trial_ends_at": clinic.trial_ends_at,
                "reason": value if action == "suspend" else None,
            },
            clinic_id=clinic.id,
        )
        await s.commit()
        forget_status(clinic.id)
        return {"id": clinic.id, **_usage(clinic, await _counts(s, clinic, now), now)}
