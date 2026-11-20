"""Doctors, weekly sessions, holidays/leave (FR-1.2, FR-1.3) and slot availability (FR-2.2)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core.clock import Clock
from clinicdesk.core.context import RequestContext
from clinicdesk.core.errors import Forbidden, PolicyViolation
from clinicdesk.modules.audit import service as audit
from clinicdesk.modules.booking.models import ACTIVE_STATUSES, Appointment  # read-only: availability
from clinicdesk.modules.scheduling import policy
from clinicdesk.modules.scheduling.models import Doctor, DoctorSession, ScheduleException
from clinicdesk.modules.scheduling.schemas import DoctorCreate, DoctorUpdate, ExceptionCreate, SessionsReplace
from clinicdesk.modules.tenancy.models import Clinic
from clinicdesk.modules.tenancy.schemas import ClinicSettings

MAX_SLOT_RANGE_DAYS = 60


async def get_doctor(s: AsyncSession, ctx: RequestContext, doctor_id: uuid.UUID, *, lock: bool = False) -> Doctor:
    q = select(Doctor).where(Doctor.id == doctor_id, Doctor.clinic_id == ctx.tenant)
    if lock:
        q = q.with_for_update()
    doctor = await s.scalar(q)
    if doctor is None:
        raise Forbidden("doctor not found in this clinic", code="forbidden_or_not_found")
    return doctor


async def create_doctor(s: AsyncSession, ctx: RequestContext, body: DoctorCreate) -> Doctor:
    doctor = Doctor(clinic_id=ctx.tenant, **body.model_dump())
    s.add(doctor)
    await s.flush()
    audit.record(s, ctx, "doctor.create", "doctor", doctor.id, after=body.model_dump())
    await s.commit()
    return doctor


async def update_doctor(s: AsyncSession, ctx: RequestContext, doctor_id: uuid.UUID, body: DoctorUpdate) -> Doctor:
    doctor = await get_doctor(s, ctx, doctor_id, lock=True)
    changes = body.model_dump(exclude_unset=True)
    before = {k: getattr(doctor, k) for k in changes}
    for k, v in changes.items():
        setattr(doctor, k, v)
    audit.record(s, ctx, "doctor.update", "doctor", doctor.id, before=before, after=changes)
    await s.commit()
    return doctor


async def list_doctors(s: AsyncSession, ctx: RequestContext) -> list[tuple[Doctor, list[DoctorSession]]]:
    doctors = (await s.scalars(select(Doctor).where(Doctor.clinic_id == ctx.tenant).order_by(Doctor.name))).all()
    sessions = (
        await s.scalars(
            select(DoctorSession)
            .where(DoctorSession.clinic_id == ctx.tenant)
            .order_by(DoctorSession.weekday, DoctorSession.start_time)
        )
    ).all()
    by_doc: dict[uuid.UUID, list[DoctorSession]] = {}
    for ses in sessions:
        by_doc.setdefault(ses.doctor_id, []).append(ses)
    return [(d, by_doc.get(d.id, [])) for d in doctors]


async def replace_sessions(
    s: AsyncSession, ctx: RequestContext, doctor_id: uuid.UUID, body: SessionsReplace
) -> list[DoctorSession]:
    """Replace the weekly template. Existing bookings are left unchanged
    (flagging bookings outside the new sessions is tracked in project-status)."""
    doctor = await get_doctor(s, ctx, doctor_id, lock=True)
    await s.execute(delete(DoctorSession).where(DoctorSession.doctor_id == doctor.id))
    rows = [DoctorSession(clinic_id=ctx.tenant, doctor_id=doctor.id, **x.model_dump()) for x in body.sessions]
    s.add_all(rows)
    audit.record(s, ctx, "doctor.sessions_replace", "doctor", doctor.id, after=body.model_dump(mode="json"))
    await s.commit()
    return rows


async def add_exception(
    s: AsyncSession, ctx: RequestContext, clock: Clock, body: ExceptionCreate
) -> tuple[ScheduleException, int]:
    """FR-1.3: holiday/leave; upcoming bookings in the range are flagged
    `needs_reschedule`, never cancelled."""
    if body.doctor_id is not None:
        await get_doctor(s, ctx, body.doctor_id)
    clinic = await s.get(Clinic, ctx.tenant)
    assert clinic is not None
    tz = ZoneInfo(clinic.timezone)
    exc = ScheduleException(clinic_id=ctx.tenant, **body.model_dump())
    s.add(exc)
    await s.flush()
    start = datetime.combine(body.start_date, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(body.end_date + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    from clinicdesk.modules.booking import service as booking  # local import: booking depends on scheduling

    flagged = await booking.flag_needs_reschedule(
        s, ctx, start=max(start, clock.now()), end=end, doctor_id=body.doctor_id, reason=body.kind
    )
    audit.record(
        s,
        ctx,
        f"schedule.{body.kind}_add",
        "schedule_exception",
        exc.id,
        after={**body.model_dump(mode="json"), "flagged_appointment_ids": flagged},
    )
    await s.commit()
    return exc, len(flagged)


async def list_exceptions(s: AsyncSession, ctx: RequestContext, from_date: date) -> list[ScheduleException]:
    q = (
        select(ScheduleException)
        .where(ScheduleException.clinic_id == ctx.tenant, ScheduleException.end_date >= from_date)
        .order_by(ScheduleException.start_date)
    )
    return list((await s.scalars(q)).all())


async def _doctor_calendar(
    s: AsyncSession, clinic_id: uuid.UUID, doctor_id: uuid.UUID, day_from: date, day_to: date
) -> tuple[list[policy.SessionTemplate], list[policy.DayOff]]:
    sessions = (await s.scalars(select(DoctorSession).where(DoctorSession.doctor_id == doctor_id))).all()
    offs = (
        await s.scalars(
            select(ScheduleException).where(
                ScheduleException.clinic_id == clinic_id,
                or_(ScheduleException.doctor_id.is_(None), ScheduleException.doctor_id == doctor_id),
                ScheduleException.start_date <= day_to,
                ScheduleException.end_date >= day_from,
            )
        )
    ).all()
    return (
        [policy.SessionTemplate(x.weekday, x.start_time, x.end_time) for x in sessions],
        [policy.DayOff(x.start_date, x.end_date) for x in offs],
    )


async def resolve_slot(s: AsyncSession, clinic: Clinic, doctor: Doctor, slot_start: datetime) -> policy.Slot:
    """The exact slot starting at `slot_start`, or PolicyViolation if no such slot exists (BR-1 alignment)."""
    tz = ZoneInfo(clinic.timezone)
    day = slot_start.astimezone(tz).date()
    sessions, offs = await _doctor_calendar(s, clinic.id, doctor.id, day, day)
    for slot in policy.generate_slots(
        sessions=sessions, days_off=offs, slot_minutes=doctor.slot_minutes, tz=tz, day_from=day, day_to=day
    ):
        if slot.start == slot_start:
            return slot
    raise PolicyViolation("no bookable slot at that time", code="invalid_slot")


async def available_slots(
    s: AsyncSession,
    ctx: RequestContext,
    clock: Clock,
    doctor_id: uuid.UUID,
    day_from: date,
    day_to: date,
    limit: int | None = None,
) -> list[policy.Slot]:
    if day_to < day_from or (day_to - day_from).days > MAX_SLOT_RANGE_DAYS:
        raise PolicyViolation("invalid date range", code="invalid_range")
    doctor = await get_doctor(s, ctx, doctor_id)
    if not doctor.is_active:
        return []
    clinic = await s.get(Clinic, ctx.tenant)
    assert clinic is not None
    tz = ZoneInfo(clinic.timezone)
    rules = ClinicSettings.from_stored(clinic.settings)
    now = clock.now()
    horizon_last = policy.local_today(now, tz) + timedelta(days=rules.booking_horizon_days)
    day_to = min(day_to, horizon_last)
    if day_to < day_from:
        return []
    sessions, offs = await _doctor_calendar(s, clinic.id, doctor.id, day_from, day_to)
    slots = policy.generate_slots(
        sessions=sessions,
        days_off=offs,
        slot_minutes=doctor.slot_minutes,
        tz=tz,
        day_from=day_from,
        day_to=day_to,
    )
    if not slots:
        return []
    taken = set(
        (
            await s.scalars(
                select(Appointment.slot_start).where(
                    Appointment.doctor_id == doctor.id,
                    Appointment.status.in_(ACTIVE_STATUSES),
                    Appointment.slot_start >= slots[0].start,
                    Appointment.slot_start <= slots[-1].start,
                )
            )
        ).all()
    )
    free = policy.free_slots(slots, taken_starts=taken, now=now, horizon_last_day=horizon_last, tz=tz)
    return free[:limit] if limit else free
