"""Missed-call recovery (FR-3.1, FR-3.2, FR-3.4, FR-3.5).

Exotel webhook → inbound_events (dedup on CallSid) → job `exotel.inbound` →
  answered? ignore · repeat within 30 min? count it, no message · else MissedCall + WhatsApp offer
  (template with "Book" / "Call me back" quick replies) + follow-up job at +15 min.
Follow-up: still pending and the caller never wrote back → `call_back_needed` (SMS link = FR-3.3, P1).
Booking from the offer → `recovered`; revenue counts only when the patient arrives (BR-11).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core import events
from clinicdesk.core.context import RequestContext, system_context
from clinicdesk.core.db import commit
from clinicdesk.core.errors import Forbidden, PolicyViolation
from clinicdesk.modules.audit import service as audit
from clinicdesk.modules.calls import policy
from clinicdesk.modules.calls.models import MissedCall
from clinicdesk.modules.jobs import service as jobs
from clinicdesk.modules.messaging import service as messaging
from clinicdesk.modules.messaging.models import Conversation, InboundEvent, Message
from clinicdesk.modules.messaging.templates import t, template_ref
from clinicdesk.modules.tenancy.models import Clinic
from clinicdesk.modules.tenancy.schemas import normalize_phone


def normalize_indian(raw: str | None) -> str | None:
    """Exotel sends numbers like 09876543210 / 919876543210 / +919876543210."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    try:
        return normalize_phone(digits if len(digits) != 12 else "+" + digits)
    except ValueError:
        return None


def _signal(s: AsyncSession, clinic_id: uuid.UUID, call_id: uuid.UUID) -> None:
    events.emit(s, events.clinic_channel(clinic_id), {"type": "calls.updated", "missed_call_id": call_id})


async def record_call(
    s: AsyncSession, clinic: Clinic, caller: str, now: datetime, *, call_sid: str | None, source: str = "exotel"
) -> MissedCall | None:
    """Returns the new MissedCall, or None when it was a repeat inside the 30-minute window (FR-3.5)."""
    ctx = system_context(clinic.id)
    await s.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"call:{clinic.id}:{caller}", 0))))
    last = await s.scalar(
        select(MissedCall)
        .where(MissedCall.clinic_id == clinic.id, MissedCall.caller_phone == caller)
        .order_by(MissedCall.last_called_at.desc())
        .limit(1)
        .with_for_update()
    )
    if last is not None and policy.is_repeat(last.last_called_at, now):
        last.repeat_count += 1
        last.last_called_at = now
        audit.record(s, ctx, "missed_call.repeat", "missed_call", last.id, after={"repeat_count": last.repeat_count})
        _signal(s, clinic.id, last.id)
        return None
    call = MissedCall(
        clinic_id=clinic.id,
        caller_phone=caller,
        first_call_sid=call_sid,
        called_at=now,
        last_called_at=now,
        source=source,
        status="pending" if source == "exotel" else "call_back_needed",
        created_at=now,
    )
    s.add(call)
    await s.flush()
    audit.record(s, ctx, "missed_call.received", "missed_call", call.id, after={"source": source})
    _signal(s, clinic.id, call.id)
    return call


async def send_offer(s: AsyncSession, clinic: Clinic, call: MissedCall, now: datetime) -> None:
    """FR-3.2: WhatsApp offer with quick replies. Patient-initiated, so transactional (Q7: not held by quiet hours)."""
    lang = await messaging.preferred_language(s, clinic, call.caller_phone)
    ids = [f"mc:{call.id}", f"mccb:{call.id}"]
    await messaging.queue_message(
        s,
        clinic_id=clinic.id,
        to_phone=call.caller_phone,
        phone_number_id="",
        category="transactional",
        key=f"missed_call_offer:{call.id}",
        run_at=now,
        session={
            "type": "buttons",
            "text": t("missed_call_offer", lang, clinic=clinic.name),
            "buttons": [
                {"id": ids[0], "title": t("btn_book_appt", lang)},
                {"id": ids[1], "title": t("btn_call_me", lang)},
            ],
        },
        template={**template_ref("missed_call_offer", lang, clinic=clinic.name), "quick_replies": ids},
    )
    call.offer_sent_at = now
    await jobs.enqueue(
        s,
        clinic_id=clinic.id,
        kind="missedcall.followup",
        run_at=now + policy.NO_REPLY_AFTER,
        dedup_key=f"missedcall.followup:{call.id}",
        payload={"missed_call_id": str(call.id)},
    )


async def handle_exotel(jc: jobs.JobContext) -> None:
    s, rt = jc.s, jc.rt  # platform (bypass) session: the clinic is unknown until resolved
    ev = await s.scalar(select(InboundEvent).where(InboundEvent.id == jc.job.payload["event_id"]).with_for_update())
    if ev is None or ev.status != "received":
        return
    now = rt.clock.now()
    p = ev.payload
    exophone = normalize_indian(p.get("CallTo") or p.get("To") or p.get("DialWhomNumber"))
    caller = normalize_indian(p.get("CallFrom") or p.get("From"))
    clinic = await s.scalar(select(Clinic).where(Clinic.exotel_number == exophone)) if exophone else None
    if clinic is None or caller is None or clinic.status == "suspended":
        ev.status, ev.processed_at, ev.error = "ignored", now, "unknown number or clinic"
        return
    if not policy.is_missed(p.get("DialCallStatus")):
        ev.status, ev.processed_at, ev.error = "ignored", now, "answered"
        return
    async with rt.db.session(clinic_id=clinic.id) as ts:
        call = await record_call(ts, clinic, caller, now, call_sid=ev.external_id)
        if call is not None:
            await send_offer(ts, clinic, call, now)
        await ts.commit()
        await jobs.flush_after_commit(ts, rt)
    ev.status, ev.processed_at = "processed", now


async def followup(jc: jobs.JobContext) -> None:
    s = jc.s
    call = await s.scalar(
        select(MissedCall).where(MissedCall.id == uuid.UUID(jc.job.payload["missed_call_id"])).with_for_update()
    )
    if call is None or call.status != "pending":
        return
    replied = await s.scalar(
        select(Message.id)
        .where(
            Message.clinic_id == call.clinic_id,
            Message.direction == "in",
            Message.at >= call.called_at,
            Message.conversation_id.in_(
                select(Conversation.id).where(
                    Conversation.clinic_id == call.clinic_id,
                    Conversation.phone == call.caller_phone,
                )
            ),
        )
        .limit(1)
    )
    if replied is None:
        call.status = "call_back_needed"
        audit.record(s, system_context(call.clinic_id), "missed_call.no_reply", "missed_call", call.id)
        _signal(s, call.clinic_id, call.id)
        # FR-3.3 (P1): SMS with a booking link goes here once a DLT-registered SMS provider is configured.


jobs.handler("exotel.inbound")(handle_exotel)
jobs.handler("missedcall.followup")(followup)


async def mark_recovered(s: AsyncSession, ctx: RequestContext, call_id: uuid.UUID, appointment_id: uuid.UUID) -> None:
    """Booking created from the offer (FR-3.4 'recovered'). Joins the caller's transaction."""
    call = await s.scalar(
        select(MissedCall).where(MissedCall.id == call_id, MissedCall.clinic_id == ctx.tenant).with_for_update()
    )
    if call is not None and call.status in ("pending", "call_back_needed"):
        call.status, call.appointment_id = "recovered", appointment_id
        audit.record(s, ctx, "missed_call.recovered", "missed_call", call.id, after={"appointment_id": appointment_id})
        _signal(s, ctx.tenant, call.id)


async def caller_requested_callback(s: AsyncSession, ctx: RequestContext, call_id: uuid.UUID, phone: str) -> bool:
    call = await s.scalar(
        select(MissedCall)
        .where(MissedCall.id == call_id, MissedCall.clinic_id == ctx.tenant, MissedCall.caller_phone == phone)
        .with_for_update()
    )
    if call is None:
        return False
    if call.status == "pending":
        call.status = "call_back_needed"
        audit.record(s, ctx, "missed_call.callback_requested", "missed_call", call.id)
        _signal(s, ctx.tenant, call.id)
    return True


async def open_call_for(s: AsyncSession, clinic_id: uuid.UUID, phone: str, now: datetime) -> MissedCall | None:
    """Most recent unresolved missed call from this number in the last 7 days (for booking attribution)."""
    return await s.scalar(
        select(MissedCall)
        .where(
            MissedCall.clinic_id == clinic_id,
            MissedCall.caller_phone == phone,
            MissedCall.status.in_(("pending", "call_back_needed")),
            MissedCall.called_at >= now - timedelta(days=7),
        )
        .order_by(MissedCall.called_at.desc())
        .limit(1)
    )


# ------------------------------------------------------------------ staff API (FR-3.4)
async def list_calls(s: AsyncSession, ctx: RequestContext, day: date | None, status: str | None) -> list[MissedCall]:
    q = (
        select(MissedCall)
        .where(MissedCall.clinic_id == ctx.tenant)
        .order_by(MissedCall.last_called_at.desc())
        .limit(300)
    )
    if status:
        q = q.where(MissedCall.status == status)
    if day is not None:
        clinic = await s.get(Clinic, ctx.tenant)
        assert clinic is not None
        start = datetime.combine(day, time.min, tzinfo=ZoneInfo(clinic.timezone)).astimezone(UTC)
        q = q.where(MissedCall.called_at >= start, MissedCall.called_at < start + timedelta(days=1))
    return list((await s.scalars(q)).all())


async def add_manual(s: AsyncSession, ctx: RequestContext, phone: str, now: datetime) -> MissedCall:
    """FRD §9 fallback when Exotel is down: the desk logs a missed call to call back (no automatic message)."""
    clinic = await s.get(Clinic, ctx.tenant)
    assert clinic is not None
    call = await record_call(s, clinic, phone, now, call_sid=None, source="manual")
    if call is None:
        raise PolicyViolation("this number is already on the list from the last 30 minutes", code="duplicate_call")
    await commit(s)
    return call


async def resolve(s: AsyncSession, ctx: RequestContext, call_id: uuid.UUID, outcome: str) -> MissedCall:
    call = await s.scalar(
        select(MissedCall).where(MissedCall.id == call_id, MissedCall.clinic_id == ctx.tenant).with_for_update()
    )
    if call is None:
        raise Forbidden("missed call not found in this clinic", code="forbidden_or_not_found")
    before = call.status
    if call.status != "recovered":
        call.status = "resolved"
    call.resolution, call.resolved_by = outcome, ctx.actor_id
    audit.record(
        s,
        ctx,
        "missed_call.resolve",
        "missed_call",
        call.id,
        before={"status": before},
        after={"status": call.status, "outcome": outcome},
    )
    _signal(s, ctx.tenant, call.id)
    await commit(s)
    return call
