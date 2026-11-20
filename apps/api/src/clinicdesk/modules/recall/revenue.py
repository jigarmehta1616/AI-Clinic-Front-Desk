"""Recovered revenue (BR-11, BR-12, FR-7.3, AC-7, AC-11).

A visit counts as recovered only when the patient ARRIVES (arrived, or token completed — a booked token
completion implies arrival) and the booking came from a recovery message (missed call, recall, no-show rebook)
within the attribution window. `UNIQUE(appointment_id)` makes the count idempotent; the fee is snapshotted at
attribution time. Every figure is an estimate and is labelled as such.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core.context import RequestContext
from clinicdesk.modules.audit import service as audit
from clinicdesk.modules.booking.models import Appointment
from clinicdesk.modules.recall import policy
from clinicdesk.modules.recall.models import Recall, RecoveryAttribution
from clinicdesk.modules.scheduling.models import Doctor
from clinicdesk.modules.tenancy.models import Clinic


async def _root_booked_at(s: AsyncSession, appt: Appointment) -> datetime:
    """A rescheduled booking keeps the time of the original booking."""
    current, hops = appt, 0
    while current.rescheduled_from_id is not None and hops < 20:
        prev = await s.get(Appointment, current.rescheduled_from_id)
        if prev is None:
            break
        current, hops = prev, hops + 1
    return current.created_at


async def _trigger_at(s: AsyncSession, appt: Appointment) -> datetime | None:
    if appt.source_ref_id is None:
        return None
    if appt.source == "recall":
        r = await s.get(Recall, appt.source_ref_id)
        return r.last_sent_at if r is not None and r.patient_id == appt.patient_id else None
    if appt.source == "noshow_rebook":
        old = await s.get(Appointment, appt.source_ref_id)
        ok = old is not None and old.status == "no_show" and old.booked_by_phone == appt.booked_by_phone
        return old.slot_end if ok else None  # type: ignore[union-attr]
    if appt.source == "missed_call":
        from clinicdesk.modules.calls.models import MissedCall

        call = await s.get(MissedCall, appt.source_ref_id)
        return call.last_called_at if call is not None and call.caller_phone == appt.booked_by_phone else None
    return None


async def attribute_arrival(s: AsyncSession, ctx: RequestContext, appt: Appointment, now: datetime) -> bool:
    """Called in the same transaction that marks the appointment arrived. Returns True if newly counted."""
    if appt.source not in policy.RECOVERY_SOURCES:
        return False
    if not policy.attributable(
        appt.source, trigger_at=await _trigger_at(s, appt), booked_at=await _root_booked_at(s, appt)
    ):
        return False
    clinic = await s.get(Clinic, appt.clinic_id)
    doctor = await s.get(Doctor, appt.doctor_id)
    assert clinic is not None and doctor is not None
    fee = policy.fee_snapshot(doctor.fee_paise, clinic.default_fee_paise)
    new_id = await s.scalar(
        insert(RecoveryAttribution)
        .values(
            clinic_id=appt.clinic_id,
            appointment_id=appt.id,
            doctor_id=appt.doctor_id,
            source=appt.source,
            source_ref_id=appt.source_ref_id,
            fee_paise=fee,
            recovered_at=now,
        )
        .on_conflict_do_nothing(index_elements=["appointment_id"])
        .returning(RecoveryAttribution.id)
    )
    if new_id is not None:
        audit.record(
            s,
            ctx,
            "revenue.attributed",
            "appointment",
            appt.id,
            after={"source": appt.source, "fee_paise": fee, "estimated": True},
        )
    return new_id is not None


def month_bounds(month: str, tz: ZoneInfo) -> tuple[datetime, datetime]:
    year, mon = (int(x) for x in month.split("-"))
    start = datetime(year, mon, 1, tzinfo=tz)
    end = datetime(year + (mon == 12), mon % 12 + 1, 1, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


async def monthly_report(s: AsyncSession, ctx: RequestContext, month: str) -> dict[str, Any]:
    """FR-7.3 / AC-11: recovered appointments by source × consultation fee, labelled as an estimate."""
    clinic = await s.get(Clinic, ctx.tenant)
    assert clinic is not None
    tz = ZoneInfo(clinic.timezone)
    start, end = month_bounds(month, tz)
    rows = await s.execute(
        select(RecoveryAttribution.source, func.count(), func.coalesce(func.sum(RecoveryAttribution.fee_paise), 0))
        .where(
            RecoveryAttribution.clinic_id == ctx.tenant,
            RecoveryAttribution.recovered_at >= start,
            RecoveryAttribution.recovered_at < end,
        )
        .group_by(RecoveryAttribution.source)
    )
    by_source = {src: {"visits": 0, "estimated_revenue_paise": 0} for src in policy.RECOVERY_SOURCES}
    for src, visits, paise in rows.all():
        by_source[src] = {"visits": int(visits), "estimated_revenue_paise": int(paise)}
    items = await s.execute(
        select(RecoveryAttribution, Doctor.name)
        .join(Doctor, Doctor.id == RecoveryAttribution.doctor_id)
        .where(
            RecoveryAttribution.clinic_id == ctx.tenant,
            RecoveryAttribution.recovered_at >= start,
            RecoveryAttribution.recovered_at < end,
        )
        .order_by(RecoveryAttribution.recovered_at)
    )
    return {
        "month": month,
        "currency": "INR",
        "estimated": True,
        "label": "Estimated recovered revenue: recovered visits × consultation fee (BR-12)",
        "total_visits": sum(v["visits"] for v in by_source.values()),
        "total_estimated_revenue_paise": sum(v["estimated_revenue_paise"] for v in by_source.values()),
        "by_source": by_source,
        "items": [
            {
                "appointment_id": a.appointment_id,
                "source": a.source,
                "doctor": name,
                "fee_paise": a.fee_paise,
                "recovered_at": a.recovered_at,
            }
            for a, name in items.all()
        ],
    }


def current_month(now: datetime, tz: ZoneInfo) -> str:
    d: date = now.astimezone(tz).date()
    return f"{d.year:04d}-{d.month:02d}"
