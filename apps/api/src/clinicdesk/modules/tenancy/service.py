"""Clinic onboarding and profile (FR-1.1), staff invites (FR-1.4)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core.clock import Clock
from clinicdesk.core.context import RequestContext
from clinicdesk.core.db import Database
from clinicdesk.core.errors import Conflict, Forbidden, NotFound, PolicyViolation
from clinicdesk.modules.audit import service as audit
from clinicdesk.modules.scheduling.models import Doctor
from clinicdesk.modules.tenancy.models import Clinic, ClinicMembership, User
from clinicdesk.modules.tenancy.schemas import (
    ClinicCreate,
    ClinicOut,
    ClinicSettings,
    ClinicUpdate,
    StaffInvite,
)

PILOT_TRIAL_DAYS = 90  # FR-9.1 free pilot plan; length = pilot duration (FRD §2)


def to_out(c: Clinic) -> ClinicOut:
    return ClinicOut(
        id=c.id,
        name=c.name,
        slug=c.slug,
        specialty=c.specialty,
        timezone=c.timezone,
        languages=list(c.languages),
        address=c.address,
        map_url=c.map_url,
        phone=c.phone,
        default_fee_paise=c.default_fee_paise,
        settings=ClinicSettings.from_stored(c.settings),
        status=c.status,
        trial_ends_at=c.trial_ends_at,
        wa_phone_number_id=c.wa_phone_number_id,
        exotel_number=c.exotel_number,
        plan=c.plan,
    )


async def create_clinic(db: Database, clock: Clock, ctx: RequestContext, body: ClinicCreate) -> Clinic:
    """Owner onboarding. Runs on the audited bypass path because the tenant does not exist yet."""
    if ctx.actor_id is None:
        raise Forbidden("sign in first")
    async with db.session(user_id=ctx.actor_id, bypass_rls=True) as s:
        clinic = Clinic(
            **body.model_dump(),
            settings=ClinicSettings().model_dump(mode="json"),
            trial_ends_at=clock.now() + timedelta(days=PILOT_TRIAL_DAYS),
        )
        s.add(clinic)
        try:
            await s.flush()
        except IntegrityError as e:
            raise Conflict("clinic code already in use", code="slug_taken") from e
        s.add(ClinicMembership(clinic_id=clinic.id, user_id=ctx.actor_id, role="owner", status="active"))
        from clinicdesk.modules.recall.service import seed_rules  # FR-1.6 specialty template

        await seed_rules(s, clinic.id, clinic.specialty)
        audit.record(
            s,
            ctx.for_clinic(clinic.id, "owner"),
            "clinic.create",
            "clinic",
            clinic.id,
            after=body.model_dump(),
        )
        await s.commit()
        return clinic


async def get_clinic(s: AsyncSession, ctx: RequestContext) -> Clinic:
    clinic = await s.get(Clinic, ctx.tenant)
    if clinic is None:
        raise NotFound("clinic not found")
    return clinic


async def update_clinic(s: AsyncSession, ctx: RequestContext, body: ClinicUpdate) -> Clinic:
    clinic = await get_clinic(s, ctx)
    changes: dict[str, Any] = body.model_dump(exclude_unset=True, mode="json")
    before = {k: getattr(clinic, k) for k in changes}
    for k, v in changes.items():
        setattr(clinic, k, v)
    audit.record(s, ctx, "clinic.update", "clinic", clinic.id, before=before, after=changes)
    await s.commit()
    return clinic


async def invite_staff(s: AsyncSession, ctx: RequestContext, body: StaffInvite) -> ClinicMembership:
    if body.role == "doctor":
        if body.doctor_id is None:
            raise PolicyViolation("doctor_id is required for the doctor role", code="doctor_id_required")
        if await s.scalar(select(Doctor.id).where(Doctor.id == body.doctor_id)) is None:
            raise Forbidden("doctor not found in this clinic", code="forbidden_or_not_found")
    elif body.doctor_id is not None:
        raise PolicyViolation("doctor_id only applies to the doctor role", code="doctor_id_not_allowed")

    user = await s.scalar(select(User).where(User.phone == body.phone))
    if user is None:
        user = User(phone=body.phone, name=body.name)
        s.add(user)
        await s.flush()
    membership = ClinicMembership(
        clinic_id=ctx.tenant, user_id=user.id, role=body.role, doctor_id=body.doctor_id, status="invited"
    )
    s.add(membership)
    try:
        await s.flush()
    except IntegrityError as e:
        raise Conflict("this number is already on the staff list", code="already_member") from e
    audit.record(
        s,
        ctx,
        "staff.invite",
        "membership",
        membership.id,
        after={"user_id": user.id, "role": body.role, "doctor_id": body.doctor_id},
    )
    await s.commit()
    return membership


async def list_staff(s: AsyncSession, ctx: RequestContext) -> list[tuple[ClinicMembership, User]]:
    rows = await s.execute(
        select(ClinicMembership, User)
        .join(User, User.id == ClinicMembership.user_id)
        .where(ClinicMembership.clinic_id == ctx.tenant)
        .order_by(ClinicMembership.created_at)
    )
    return list(rows.all())


async def membership_exists(s: AsyncSession, clinic_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    q = select(ClinicMembership.id).where(ClinicMembership.clinic_id == clinic_id, ClinicMembership.user_id == user_id)
    return await s.scalar(q) is not None
