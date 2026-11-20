"""Today view (FR-7.1): per doctor — appointments, tokens, arrivals, no-shows — plus open chats. Read-only."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core.context import RequestContext
from clinicdesk.modules.booking.models import UPCOMING_STATUSES, Appointment
from clinicdesk.modules.messaging.models import HandoverTicket
from clinicdesk.modules.queue.models import QueueEntry, QueueSession
from clinicdesk.modules.recall.models import Recall
from clinicdesk.modules.scheduling.models import Doctor
from clinicdesk.modules.tenancy.models import Clinic

APPT_STATUSES = ("booked", "confirmed", "arrived", "completed", "no_show", "cancelled")
TOKEN_STATUSES = ("waiting", "called", "skipped", "completed")


async def today(s: AsyncSession, ctx: RequestContext, day: date, now: datetime) -> dict[str, Any]:
    clinic = await s.get(Clinic, ctx.tenant)
    assert clinic is not None
    tz = ZoneInfo(clinic.timezone)
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
    end = start + timedelta(days=1)

    doctors_q = select(Doctor).where(Doctor.clinic_id == ctx.tenant).order_by(Doctor.name)
    if ctx.role == "doctor":
        doctors_q = doctors_q.where(Doctor.id == ctx.doctor_id)
    doctors = list((await s.scalars(doctors_q)).all())
    ids = [d.id for d in doctors]

    appt_counts: dict[tuple[Any, str], int] = {}
    for doctor_id, status, n in (
        await s.execute(
            select(Appointment.doctor_id, Appointment.status, func.count())
            .where(
                Appointment.clinic_id == ctx.tenant,
                Appointment.doctor_id.in_(ids),
                Appointment.slot_start >= start,
                Appointment.slot_start < end,
            )
            .group_by(Appointment.doctor_id, Appointment.status)
        )
    ).all():
        appt_counts[(doctor_id, status)] = n

    token_counts: dict[tuple[Any, str], int] = {}
    for doctor_id, status, n in (
        await s.execute(
            select(QueueSession.doctor_id, QueueEntry.status, func.count())
            .join(QueueSession, QueueSession.id == QueueEntry.queue_session_id)
            .where(
                QueueSession.clinic_id == ctx.tenant, QueueSession.session_date == day, QueueSession.doctor_id.in_(ids)
            )
            .group_by(QueueSession.doctor_id, QueueEntry.status)
        )
    ).all():
        token_counts[(doctor_id, status)] = n

    current: dict[Any, int] = {}
    for doctor_id, token_no in (
        await s.execute(
            select(QueueSession.doctor_id, QueueEntry.token_no)
            .join(QueueEntry, QueueEntry.id == QueueSession.current_entry_id)
            .where(
                QueueSession.clinic_id == ctx.tenant, QueueSession.session_date == day, QueueSession.doctor_id.in_(ids)
            )
            .order_by(QueueSession.start_time)
        )
    ).all():
        current[doctor_id] = token_no

    open_tickets = (
        await s.execute(
            select(HandoverTicket.reason, func.count())
            .where(HandoverTicket.clinic_id == ctx.tenant, HandoverTicket.status == "open")
            .group_by(HandoverTicket.reason)
        )
    ).all()
    needs_reschedule = await s.scalar(
        select(func.count()).where(
            Appointment.clinic_id == ctx.tenant,
            Appointment.needs_reschedule.is_(True),
            Appointment.status.in_(UPCOMING_STATUSES),
            Appointment.slot_start > now,
        )
    )
    recalls_due = await s.scalar(
        select(func.count()).where(
            Recall.clinic_id == ctx.tenant, Recall.due_date == day, Recall.status.in_(("scheduled", "sent"))
        )
    )
    from clinicdesk.modules.calls.models import MissedCall

    call_back = await s.scalar(
        select(func.count()).where(MissedCall.clinic_id == ctx.tenant, MissedCall.status == "call_back_needed")
    )
    missed_today = await s.scalar(
        select(func.count()).where(
            MissedCall.clinic_id == ctx.tenant, MissedCall.called_at >= start, MissedCall.called_at < end
        )
    )
    return {
        "missed_calls_today": int(missed_today or 0),
        "call_backs_needed": int(call_back or 0),
        "day": day,
        "doctors": [
            {
                "doctor_id": d.id,
                "name": d.name,
                "is_active": d.is_active,
                "appointments": {st: appt_counts.get((d.id, st), 0) for st in APPT_STATUSES},
                "tokens": {st: token_counts.get((d.id, st), 0) for st in TOKEN_STATUSES},
                "current_token": current.get(d.id),
            }
            for d in doctors
        ],
        "open_chats": sum(n for _, n in open_tickets),
        "emergencies": sum(n for reason, n in open_tickets if reason == "emergency"),
        "needs_reschedule": int(needs_reschedule or 0),
        "recalls_due": int(recalls_due or 0),
    }
