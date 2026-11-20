"""Conversations, outbox and dispatch (BR-7, BR-8, BR-9, FR-2.9, NFR-4).

Send path: `queue_message` writes an outbox row + a `wa.send` job in the caller's transaction.
The dispatcher re-checks everything at send time and is at-most-once per outbox row:
  1. lock row; skip if already terminal; a row left in `sending` by a crashed worker → failed
     `delivery_unknown` (never risk a duplicate patient message);
  2. non-transactional: defer out of quiet hours (BR-7), skip if opted out / no consent (BR-8, DP-2);
  3. choose session message inside the 24 h window, else the approved template (BR-9), else fail;
  4. mark `sending` + commit, call the provider, then record `sent` / retry / `failed`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core import events
from clinicdesk.core.config import Settings
from clinicdesk.integrations.whatsapp import (
    PermanentSendError,
    TransientSendError,
    build_payload,
    text_of,
)
from clinicdesk.modules.jobs import service as jobs
from clinicdesk.modules.messaging.models import Conversation, Message, OutboxMessage
from clinicdesk.modules.messaging.quiet_hours import adjust_send_time
from clinicdesk.modules.patients.models import ConsentEvent, Patient
from clinicdesk.modules.tenancy.models import Clinic
from clinicdesk.modules.tenancy.schemas import ClinicSettings

WINDOW = timedelta(hours=24)
ORDER_WAIT = timedelta(seconds=2)
PURPOSE_FOR_CATEGORY = {"reminder": "reminders", "recall": "recalls", "promo": "recalls"}


def sender_number(clinic: Clinic | None, settings: Settings) -> str:
    """Clinic's own number (FR-1.5) or the shared pilot number (open question Q1)."""
    return (clinic.wa_phone_number_id if clinic else None) or settings.whatsapp_shared_phone_number_id or ""


async def get_or_create_conversation(
    s: AsyncSession, clinic_id: uuid.UUID, phone: str, phone_number_id: str | None, *, lock: bool = True
) -> Conversation:
    await s.execute(
        insert(Conversation)
        .values(clinic_id=clinic_id, phone=phone, phone_number_id=phone_number_id)
        .on_conflict_do_nothing(index_elements=["clinic_id", "phone"])
    )
    q = select(Conversation).where(Conversation.clinic_id == clinic_id, Conversation.phone == phone)
    conv = await s.scalar(q.with_for_update() if lock else q)
    assert conv is not None
    return conv


def in_window(conv: Conversation | None, now: datetime) -> bool:
    return bool(conv and conv.last_inbound_at and now - conv.last_inbound_at < WINDOW)


async def queue_message(
    s: AsyncSession,
    *,
    clinic_id: uuid.UUID | None,
    to_phone: str,
    phone_number_id: str,
    category: str,
    key: str,
    run_at: datetime,
    session: dict[str, Any] | None = None,
    template: dict[str, Any] | None = None,
    patient_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    sent_by_user_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Idempotent on `key`: returns None if this message was already queued."""
    row_id = await s.scalar(
        insert(OutboxMessage)
        .values(
            clinic_id=clinic_id,
            conversation_id=conversation_id,
            patient_id=patient_id,
            to_phone=to_phone,
            phone_number_id=phone_number_id,
            category=category,
            session_payload=session,
            template=template,
            idempotency_key=key,
            sent_by_user_id=sent_by_user_id,
            created_at=run_at,  # logical send time on the app clock (BR-8 cap looks at it)
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(OutboxMessage.id)
    )
    if row_id is None:
        return None
    await jobs.enqueue(
        s,
        clinic_id=clinic_id,
        kind="wa.send",
        run_at=run_at,
        dedup_key=f"wa.send:{row_id}",
        payload={"outbox_id": str(row_id)},
    )
    return uuid.UUID(str(row_id))


async def preferred_language(s: AsyncSession, clinic: Clinic, phone: str) -> str:
    lang = await s.scalar(
        select(Conversation.language).where(Conversation.clinic_id == clinic.id, Conversation.phone == phone)
    )
    if not lang:
        lang = await s.scalar(
            select(Patient.language)
            .where(Patient.clinic_id == clinic.id, Patient.phone == phone, Patient.language.is_not(None))
            .limit(1)
        )
    return lang or (clinic.languages[0] if clinic.languages else "en")


async def opted_out(s: AsyncSession, clinic_id: uuid.UUID, phone: str) -> bool:
    conv = await s.scalar(
        select(Conversation.opted_out_at).where(Conversation.clinic_id == clinic_id, Conversation.phone == phone)
    )
    if conv is not None:
        return True
    flagged = await s.scalar(
        select(Patient.id).where(
            Patient.clinic_id == clinic_id, Patient.phone == phone, Patient.opted_out_at.is_not(None)
        )
    )
    return flagged is not None


async def has_consent(s: AsyncSession, clinic_id: uuid.UUID, phone: str, purpose: str) -> bool:
    """Latest explicit consent for `purpose` on any patient under this number (DP-2). No record = no."""
    latest = await s.scalar(
        select(ConsentEvent.granted)
        .join(Patient, Patient.id == ConsentEvent.patient_id)
        .where(Patient.clinic_id == clinic_id, Patient.phone == phone, ConsentEvent.purpose == purpose)
        .order_by(ConsentEvent.at.desc())
        .limit(1)
    )
    return bool(latest)


async def dispatch(jc: jobs.JobContext) -> None:
    s, rt = jc.s, jc.rt
    now = rt.clock.now()
    ob = await s.scalar(
        select(OutboxMessage).where(OutboxMessage.id == uuid.UUID(jc.job.payload["outbox_id"])).with_for_update()
    )
    if ob is None or ob.status in ("sent", "failed", "skipped", "cancelled"):
        return
    if ob.status == "sending":
        ob.status, ob.last_error = "failed", "delivery_unknown: worker stopped mid-send; not retried"
        return

    if ob.category == "transactional":
        # Preserve reply order per recipient even with parallel workers: wait for earlier replies.
        earlier = await s.scalar(
            select(OutboxMessage.id)
            .where(
                OutboxMessage.to_phone == ob.to_phone,
                OutboxMessage.clinic_id.is_not_distinct_from(ob.clinic_id),
                OutboxMessage.category == "transactional",
                OutboxMessage.status.in_(("pending", "sending")),
                OutboxMessage.seq < ob.seq,
            )
            .limit(1)
        )
        if earlier is not None:
            raise jobs.Reschedule(now + ORDER_WAIT, "waiting_for_earlier_reply")

    clinic = await s.get(Clinic, ob.clinic_id) if ob.clinic_id else None
    tz = ZoneInfo(clinic.timezone if clinic else "Asia/Kolkata")
    rules = ClinicSettings.from_stored(clinic.settings if clinic else None)
    if ob.category != "transactional" and clinic is not None:
        allowed_at = adjust_send_time(now, ob.category, tz=tz, start=rules.quiet_start, end=rules.quiet_end)  # type: ignore[arg-type]
        if allowed_at is not None and allowed_at > now:
            raise jobs.Reschedule(allowed_at, "quiet_hours")
        if await opted_out(s, clinic.id, ob.to_phone):
            ob.status, ob.last_error = "skipped", "opted_out"
            return
        if not await has_consent(s, clinic.id, ob.to_phone, PURPOSE_FOR_CATEGORY[ob.category]):
            ob.status, ob.last_error = "skipped", "no_consent"
            return
    if not ob.phone_number_id:  # domain code may leave it to dispatch time
        ob.phone_number_id = sender_number(clinic, rt.settings)
    if not ob.phone_number_id:
        ob.status, ob.last_error = "failed", "no_sender_number: clinic WhatsApp number not configured"
        return

    conv = None
    if clinic is not None:
        conv = await s.scalar(
            select(Conversation).where(Conversation.clinic_id == clinic.id, Conversation.phone == ob.to_phone)
        )
    if in_window(conv, now) and ob.session_payload is not None:
        payload = build_payload(ob.to_phone, ob.session_payload, None)
    elif ob.template is not None:
        payload = build_payload(ob.to_phone, None, ob.template)
    else:
        ob.status, ob.last_error = "failed", "outside_24h_window: no approved template for this message (BR-9)"
        return

    ob.status = "sending"
    ob.attempts += 1
    await s.commit()  # phase 1 durable: a crash from here on can never cause a second send
    try:
        provider_id = await rt.whatsapp.send(ob.phone_number_id, payload)
    except TransientSendError as e:
        give_up = jc.job.attempts >= jc.job.max_attempts
        ob.status = "failed" if give_up else "pending"
        ob.last_error = f"transient: {e}"
        await s.commit()
        if not give_up:
            raise
        return
    except PermanentSendError as e:
        ob.status, ob.last_error = "failed", f"{e.code}: {e}"
        return

    ob.status, ob.provider_message_id, ob.sent_at, ob.last_error = "sent", provider_id, now, None
    if clinic is not None:
        if conv is None:
            conv = await get_or_create_conversation(s, clinic.id, ob.to_phone, ob.phone_number_id)
        conv.last_outbound_at = now
        # Staff watching this thread see the message appear (signal only; they refetch over REST).
        events.emit(s, events.clinic_channel(clinic.id), {"type": "inbox.message", "conversation_id": conv.id})
        # Bookkeeping must never undo a successful send: ignore a duplicate provider id.
        await s.execute(
            insert(Message)
            .values(
                clinic_id=clinic.id,
                conversation_id=conv.id,
                direction="out",
                kind=payload["type"],
                body={"text": text_of(payload), "payload": ob.session_payload or ob.template},
                provider_message_id=provider_id,
                status="sent",
                sent_by_user_id=ob.sent_by_user_id,
                at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["provider_message_id"], index_where=Message.provider_message_id.is_not(None)
            )
        )


jobs.handler("wa.send")(dispatch)


async def apply_status(s: AsyncSession, provider_message_id: str, status: str, error: str | None) -> None:
    """Delivery receipts from the webhook (sent/delivered/read/failed)."""
    await s.execute(
        update(OutboxMessage)
        .where(OutboxMessage.provider_message_id == provider_message_id)
        .values(delivery_status=status, last_error=error if error else OutboxMessage.last_error)
    )
    await s.execute(update(Message).where(Message.provider_message_id == provider_message_id).values(status=status))


async def recent_messages(s: AsyncSession, conversation_id: uuid.UUID, limit: int = 100) -> list[Message]:
    rows = await s.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq.desc()).limit(limit)
    )
    return list(reversed(rows.all()))


async def patients_for_phone(s: AsyncSession, clinic_id: uuid.UUID, phone: str) -> list[Patient]:
    rows = await s.scalars(
        select(Patient).where(Patient.clinic_id == clinic_id, or_(Patient.phone == phone)).order_by(Patient.created_at)
    )
    return list(rows.all())
