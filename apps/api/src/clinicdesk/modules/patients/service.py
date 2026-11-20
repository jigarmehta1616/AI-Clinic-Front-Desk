"""Patients and family members (FR-2.3, FR-2.8, FR-7.2)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core.context import RequestContext
from clinicdesk.core.db import Database, commit
from clinicdesk.core.errors import Conflict, Forbidden
from clinicdesk.modules.audit import service as audit
from clinicdesk.modules.patients.models import ConsentEvent, Patient
from clinicdesk.modules.patients.schemas import ConsentIn, PatientCreate, PatientUpdate


async def get_patient(
    s: AsyncSession, ctx: RequestContext, patient_id: uuid.UUID, *, db: Database | None = None
) -> Patient:
    """Scoped lookup. Missing or other-clinic ids are indistinguishable → 403 (AC-10).

    The denial is audit-logged when `db` is given."""
    patient = await s.scalar(select(Patient).where(Patient.id == patient_id, Patient.clinic_id == ctx.tenant))
    if patient is None:
        if db is not None:
            await audit.record_now(db, ctx, "access_denied", "patient", patient_id)
        raise Forbidden("patient not found in this clinic", code="forbidden_or_not_found")
    return patient


async def create_patient(s: AsyncSession, ctx: RequestContext, body: PatientCreate) -> Patient:
    if body.account_holder_id is not None:
        holder = await get_patient(s, ctx, body.account_holder_id)
        if holder.phone != body.phone:
            raise Conflict("family members must share the account holder's number", code="family_phone_mismatch")
    patient = Patient(clinic_id=ctx.tenant, **body.model_dump())
    try:
        async with s.begin_nested():
            s.add(patient)
            await s.flush()
    except IntegrityError as e:
        raise Conflict("a patient with this name and number already exists", code="patient_exists") from e
    audit.record(s, ctx, "patient.create", "patient", patient.id, after={"language": body.language})
    await commit(s)
    return patient


async def update_patient(s: AsyncSession, ctx: RequestContext, patient_id: uuid.UUID, body: PatientUpdate) -> Patient:
    patient = await get_patient(s, ctx, patient_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(patient, k, v)
    # Field names only: avoid copying personal data into the audit log.
    audit.record(s, ctx, "patient.update", "patient", patient.id, after={"fields": sorted(changes)})
    await commit(s)
    return patient


async def contacts(s: AsyncSession, ctx: RequestContext, ids: set[uuid.UUID]) -> dict[uuid.UUID, Patient]:
    """Patients by id for staff list views (one query, tenant-scoped)."""
    if not ids:
        return {}
    rows = await s.scalars(select(Patient).where(Patient.clinic_id == ctx.tenant, Patient.id.in_(ids)))
    return {p.id: p for p in rows.all()}


async def by_phones(s: AsyncSession, ctx: RequestContext, phones: set[str]) -> dict[str, Patient]:
    """First-registered patient per phone (account holder), one query."""
    if not phones:
        return {}
    rows = await s.scalars(
        select(Patient)
        .where(Patient.clinic_id == ctx.tenant, Patient.phone.in_(phones))
        .order_by(Patient.created_at.desc())
    )
    return {p.phone: p for p in rows.all()}  # later rows overwrite → earliest wins


async def search(s: AsyncSession, ctx: RequestContext, q: str | None, limit: int = 50) -> list[Patient]:
    stmt = select(Patient).where(Patient.clinic_id == ctx.tenant).order_by(Patient.name).limit(limit)
    if q:
        term = q.strip()
        digits = "".join(ch for ch in term if ch.isdigit())
        like = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conds = [Patient.name.ilike(f"%{like}%", escape="\\")]
        if len(digits) >= 4:
            conds.append(Patient.phone.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conds))
    return list((await s.scalars(stmt)).all())


async def record_consent(
    s: AsyncSession, ctx: RequestContext, now: datetime, patient_id: uuid.UUID, body: ConsentIn, notice_version: str
) -> ConsentEvent:
    """DP-2: staff record consent given verbally / on paper for reminders or recalls (append-only history)."""
    patient = await get_patient(s, ctx, patient_id)
    event = ConsentEvent(
        clinic_id=ctx.tenant,
        patient_id=patient.id,
        purpose=body.purpose,
        granted=body.granted,
        channel="dashboard",
        notice_version=notice_version,
        at=now,
    )
    s.add(event)
    audit.record(s, ctx, f"consent.{body.purpose}_{'granted' if body.granted else 'withdrawn'}", "patient", patient.id)
    await commit(s)
    return event


async def latest_consents(s: AsyncSession, ctx: RequestContext, patient_id: uuid.UUID) -> dict[str, bool]:
    """Most recent consent decision per purpose for one patient (DP-2 history is kept in full)."""
    rows = await s.execute(
        select(ConsentEvent.purpose, ConsentEvent.granted)
        .where(ConsentEvent.clinic_id == ctx.tenant, ConsentEvent.patient_id == patient_id)
        .order_by(ConsentEvent.purpose, ConsentEvent.at.desc(), ConsentEvent.created_at.desc())
        .ext(distinct_on(ConsentEvent.purpose))
    )
    return {purpose: granted for purpose, granted in rows.all()}
