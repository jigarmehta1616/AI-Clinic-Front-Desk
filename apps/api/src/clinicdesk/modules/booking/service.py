"""Appointments: book, reschedule, cancel, status changes (FR-2.4, FR-5.2, BR-1..BR-4, BR-13).

Concurrency (ADR-0003):
* BR-1 is guaranteed by the partial unique index `uq_appt_active_slot`; a losing insert → SlotTaken.
* BR-4 count-then-insert is serialised per (clinic, doctor, phone) with a transaction-scoped advisory lock.
* Mutations of an existing appointment lock its row first (`FOR UPDATE`), then take the advisory lock.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core.clock import Clock
from clinicdesk.core.context import RequestContext
from clinicdesk.core.db import Database, commit
from clinicdesk.core.errors import Forbidden, PolicyViolation, SlotTaken
from clinicdesk.modules.audit import service as audit
from clinicdesk.modules.booking import policy
from clinicdesk.modules.booking.models import UPCOMING_STATUSES, Appointment
from clinicdesk.modules.booking.schemas import BookIn, CancelIn, RescheduleIn
from clinicdesk.modules.patients import service as patients
from clinicdesk.modules.queue import service as queue
from clinicdesk.modules.recall import reminders, revenue
from clinicdesk.modules.recall import service as recall_service
from clinicdesk.modules.scheduling import service as scheduling
from clinicdesk.modules.tenancy.models import Clinic
from clinicdesk.modules.tenancy.schemas import ClinicSettings


def snapshot(a: Appointment) -> dict[str, Any]:
    return {
        "status": a.status,
        "doctor_id": a.doctor_id,
        "patient_id": a.patient_id,
        "slot_start": a.slot_start,
        "source": a.source,
    }


async def _clinic(s: AsyncSession, ctx: RequestContext) -> tuple[Clinic, ZoneInfo, ClinicSettings]:
    clinic = await s.get(Clinic, ctx.tenant)
    assert clinic is not None
    return clinic, ZoneInfo(clinic.timezone), ClinicSettings.from_stored(clinic.settings)


def _assert_doctor_scope(ctx: RequestContext, doctor_id: uuid.UUID) -> None:
    """Doctors act only on their own appointments (FRD §3)."""
    if ctx.role == "doctor" and ctx.doctor_id != doctor_id:
        raise Forbidden("doctors can only change their own appointments", code="not_own_appointment")


async def _lock_phone_doctor(s: AsyncSession, clinic_id: uuid.UUID, doctor_id: uuid.UUID, phone: str) -> None:
    key = f"book:{clinic_id}:{doctor_id}:{phone}"
    await s.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


async def _count_upcoming(
    s: AsyncSession, doctor_id: uuid.UUID, phone: str, now: datetime, exclude_id: uuid.UUID | None = None
) -> int:
    q = select(func.count()).where(
        Appointment.doctor_id == doctor_id,
        Appointment.booked_by_phone == phone,
        Appointment.status.in_(UPCOMING_STATUSES),
        Appointment.slot_start > now,
    )
    if exclude_id is not None:
        q = q.where(Appointment.id != exclude_id)
    return int(await s.scalar(q) or 0)


async def _insert(s: AsyncSession, appt: Appointment) -> None:
    try:
        async with s.begin_nested():  # savepoint: a lost race must not abort the caller's transaction
            s.add(appt)
            await s.flush()
    except IntegrityError as e:
        if "uq_appt_active_slot" in str(e.orig):
            raise SlotTaken("that slot was just taken", details={"slot_start": appt.slot_start.isoformat()}) from e
        raise


async def get_for_update(
    s: AsyncSession, ctx: RequestContext, appointment_id: uuid.UUID, *, db: Database | None = None
) -> Appointment:
    appt = await s.scalar(
        select(Appointment)
        .where(Appointment.id == appointment_id, Appointment.clinic_id == ctx.tenant)
        .with_for_update()
    )
    if appt is None:
        if db is not None:
            await audit.record_now(db, ctx, "access_denied", "appointment", appointment_id)
        raise Forbidden("appointment not found in this clinic", code="forbidden_or_not_found")
    return appt


async def book(s: AsyncSession, ctx: RequestContext, clock: Clock, body: BookIn) -> Appointment:
    clinic, tz, rules = await _clinic(s, ctx)
    now = clock.now()
    doctor = await scheduling.get_doctor(s, ctx, body.doctor_id)
    if not doctor.is_active:
        raise PolicyViolation("doctor is not taking bookings", code="doctor_inactive")
    patient = await patients.get_patient(s, ctx, body.patient_id)
    policy.check_bookable(body.slot_start, now=now, tz=tz, rules=rules)
    slot = await scheduling.resolve_slot(s, clinic, doctor, body.slot_start)

    await _lock_phone_doctor(s, clinic.id, doctor.id, patient.phone)
    policy.check_upcoming_limit(await _count_upcoming(s, doctor.id, patient.phone, now), rules=rules)

    source = "assistant" if ctx.channel == "whatsapp" and body.source == "staff" else body.source
    appt = Appointment(
        clinic_id=clinic.id,
        doctor_id=doctor.id,
        patient_id=patient.id,
        booked_by_phone=patient.phone,
        slot_start=slot.start,
        slot_end=slot.end,
        status="booked",
        created_at=now,  # app clock: attribution windows compare against it (BR-11)
        source=source,
        source_ref_id=body.source_ref_id,
        visit_type=body.visit_type,
    )
    await _insert(s, appt)
    audit.record(s, ctx, "appointment.book", "appointment", appt.id, after=snapshot(appt))
    await reminders.schedule_for(s, appt, now)  # FR-5.1
    if appt.source == "recall" and appt.source_ref_id is not None:
        await recall_service.mark_booked(s, ctx, appt.source_ref_id, appt.id)
    if appt.source == "missed_call" and appt.source_ref_id is not None:
        from clinicdesk.modules.calls import service as calls  # calls → messaging → … avoid import cycle

        await calls.mark_recovered(s, ctx, appt.source_ref_id, appt.id)
    await commit(s)
    return appt


async def reschedule(
    s: AsyncSession,
    ctx: RequestContext,
    clock: Clock,
    appointment_id: uuid.UUID,
    body: RescheduleIn,
    *,
    db: Database | None = None,
) -> Appointment:
    """FR-2.4 / AC-4: new appointment + old marked `rescheduled` in one transaction;
    the old slot is freed on commit."""
    clinic, tz, rules = await _clinic(s, ctx)
    now = clock.now()
    old = await get_for_update(s, ctx, appointment_id, db=db)
    _assert_doctor_scope(ctx, old.doctor_id)
    policy.check_transition(old.status, "rescheduled")
    policy.check_changeable(old.slot_start, now=now, rules=rules)
    doctor = await scheduling.get_doctor(s, ctx, body.doctor_id or old.doctor_id)
    if not doctor.is_active:
        raise PolicyViolation("doctor is not taking bookings", code="doctor_inactive")
    if doctor.id == old.doctor_id and body.slot_start == old.slot_start:
        raise PolicyViolation("new slot equals the current slot", code="same_slot")
    policy.check_bookable(body.slot_start, now=now, tz=tz, rules=rules)
    slot = await scheduling.resolve_slot(s, clinic, doctor, body.slot_start)

    await _lock_phone_doctor(s, clinic.id, doctor.id, old.booked_by_phone)
    upcoming = await _count_upcoming(s, doctor.id, old.booked_by_phone, now, exclude_id=old.id)
    policy.check_upcoming_limit(upcoming, rules=rules)

    before = snapshot(old)
    old.status = "rescheduled"
    old.needs_reschedule = False
    await s.flush()
    new = Appointment(
        clinic_id=clinic.id,
        doctor_id=doctor.id,
        patient_id=old.patient_id,
        booked_by_phone=old.booked_by_phone,
        slot_start=slot.start,
        slot_end=slot.end,
        status="booked",
        created_at=now,  # app clock: attribution windows compare against it (BR-11)
        source=old.source,
        source_ref_id=old.source_ref_id,
        visit_type=old.visit_type,
        rescheduled_from_id=old.id,
    )
    await _insert(s, new)
    await reminders.schedule_for(s, new, now)
    audit.record(s, ctx, "appointment.reschedule_from", "appointment", old.id, before=before, after=snapshot(old))
    audit.record(
        s,
        ctx,
        "appointment.reschedule_to",
        "appointment",
        new.id,
        after={**snapshot(new), "rescheduled_from_id": old.id},
    )
    await commit(s)
    return new


async def cancel(
    s: AsyncSession,
    ctx: RequestContext,
    clock: Clock,
    appointment_id: uuid.UUID,
    body: CancelIn,
    *,
    db: Database | None = None,
) -> Appointment:
    _, _, rules = await _clinic(s, ctx)
    now = clock.now()
    appt = await get_for_update(s, ctx, appointment_id, db=db)
    _assert_doctor_scope(ctx, appt.doctor_id)
    policy.check_transition(appt.status, "cancelled")
    override = body.staff_override and ctx.actor_type == "user"
    policy.check_changeable(appt.slot_start, now=now, rules=rules, staff_override=override)
    before = snapshot(appt)
    appt.status = "cancelled"
    appt.cancelled_at = now
    appt.needs_reschedule = False
    audit.record(
        s,
        ctx,
        "appointment.cancel",
        "appointment",
        appt.id,
        before=before,
        after={**snapshot(appt), "reason": body.reason, "staff_override": override},
    )
    await commit(s)
    return appt


async def set_status(
    s: AsyncSession,
    ctx: RequestContext,
    clock: Clock,
    appointment_id: uuid.UUID,
    target: str,
    *,
    db: Database | None = None,
) -> Appointment:
    """Confirm / arrived / completed / no-show (FR-5.1, FR-5.2)."""
    _, tz, _ = await _clinic(s, ctx)
    now = clock.now()
    appt = await get_for_update(s, ctx, appointment_id, db=db)
    _assert_doctor_scope(ctx, appt.doctor_id)
    policy.check_transition(appt.status, target)
    before = snapshot(appt)
    if target == "arrived":
        policy.check_arrival_day(appt.slot_start, now=now, tz=tz)
        appt.arrived_at = now
        await queue.add_arrival(
            s,
            ctx,
            clock,
            appointment_id=appt.id,
            doctor_id=appt.doctor_id,
            patient_id=appt.patient_id,
            phone=appt.booked_by_phone,
            slot_start=appt.slot_start,
        )
        await revenue.attribute_arrival(s, ctx, appt, now)  # BR-11
    elif target == "completed":
        appt.completed_at = now
        await recall_service.on_visit_completed(s, ctx, appt, now)  # FR-6.1
    elif target == "no_show" and now < appt.slot_start:
        raise PolicyViolation("cannot mark no-show before the appointment time", code="too_early_for_no_show")
    appt.status = target
    audit.record(s, ctx, f"appointment.{target}", "appointment", appt.id, before=before, after=snapshot(appt))
    await commit(s)
    return appt


async def complete_from_queue(s: AsyncSession, ctx: RequestContext, clock: Clock, appointment_id: uuid.UUID) -> None:
    """Token completed in the queue → appointment completed. Joins the caller's transaction."""
    appt = await get_for_update(s, ctx, appointment_id)
    if appt.status != "arrived":
        return  # already completed or changed by staff; nothing to do (idempotent)
    before = snapshot(appt)
    appt.status = "completed"
    appt.completed_at = clock.now()
    await recall_service.on_visit_completed(s, ctx, appt, clock.now())  # FR-6.1
    audit.record(s, ctx, "appointment.completed", "appointment", appt.id, before=before, after=snapshot(appt))


async def flag_needs_reschedule(
    s: AsyncSession,
    ctx: RequestContext,
    *,
    start: datetime,
    end: datetime,
    doctor_id: uuid.UUID | None,
    reason: str,
) -> list[uuid.UUID]:
    """FR-1.3. Joins the caller's transaction (no commit)."""
    q = (
        update(Appointment)
        .where(
            Appointment.clinic_id == ctx.tenant,
            Appointment.status.in_(UPCOMING_STATUSES),
            Appointment.slot_start >= start,
            Appointment.slot_start < end,
        )
        .values(needs_reschedule=True)
        .returning(Appointment.id)
    )
    if doctor_id is not None:
        q = q.where(Appointment.doctor_id == doctor_id)
    ids = list((await s.scalars(q)).all())
    for appt_id in ids:
        audit.record(s, ctx, "appointment.flag_reschedule", "appointment", appt_id, after={"reason": reason})
    return ids


async def list_for_patient(
    s: AsyncSession, ctx: RequestContext, patient_id: uuid.UUID, limit: int = 100
) -> list[Appointment]:
    """FR-7.2 visit history and upcoming appointments (doctors see only their own)."""
    q = (
        select(Appointment)
        .where(Appointment.clinic_id == ctx.tenant, Appointment.patient_id == patient_id)
        .order_by(Appointment.slot_start.desc())
        .limit(limit)
    )
    if ctx.role == "doctor":
        q = q.where(Appointment.doctor_id == ctx.doctor_id)
    return list((await s.scalars(q)).all())


async def list_for_day(
    s: AsyncSession, ctx: RequestContext, day: date, doctor_id: uuid.UUID | None
) -> list[Appointment]:
    _, tz, _ = await _clinic(s, ctx)
    if ctx.role == "doctor":
        doctor_id = ctx.doctor_id  # doctors see only their own schedule
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
    q = (
        select(Appointment)
        .where(
            Appointment.clinic_id == ctx.tenant,
            Appointment.slot_start >= start,
            Appointment.slot_start < start + timedelta(days=1),
        )
        .order_by(Appointment.slot_start)
    )
    if doctor_id is not None:
        q = q.where(Appointment.doctor_id == doctor_id)
    return list((await s.scalars(q)).all())
