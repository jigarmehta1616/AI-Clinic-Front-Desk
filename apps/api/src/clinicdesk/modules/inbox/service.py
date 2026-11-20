"""Staff inbox (FR-8.1, FR-8.2, FR-8.4)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core import events
from clinicdesk.core.clock import Clock
from clinicdesk.core.config import Settings
from clinicdesk.core.context import RequestContext
from clinicdesk.core.db import Database
from clinicdesk.core.errors import Forbidden, PolicyViolation
from clinicdesk.modules.audit import service as audit
from clinicdesk.modules.messaging import service as messaging
from clinicdesk.modules.messaging.models import Conversation, HandoverTicket, Message
from clinicdesk.modules.patients.models import Patient
from clinicdesk.modules.tenancy.models import Clinic


@dataclass(frozen=True, slots=True)
class InboxItem:
    ticket: HandoverTicket
    conversation: Conversation
    patient_names: list[str]
    last_message: str | None
    last_at: datetime | None


async def list_open(s: AsyncSession, ctx: RequestContext, status: str = "open", limit: int = 100) -> list[InboxItem]:
    rows = await s.execute(
        select(HandoverTicket, Conversation)
        .join(Conversation, Conversation.id == HandoverTicket.conversation_id)
        .where(HandoverTicket.clinic_id == ctx.tenant, HandoverTicket.status == status)
        .order_by((HandoverTicket.reason == "emergency").desc(), HandoverTicket.opened_at)
        .limit(limit)
    )
    items = []
    for ticket, conv in rows.all():
        last = await s.scalar(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.seq.desc()).limit(1)
        )
        names = (
            await s.scalars(select(Patient.name).where(Patient.clinic_id == ctx.tenant, Patient.phone == conv.phone))
        ).all()
        items.append(
            InboxItem(
                ticket, conv, list(names), (last.body or {}).get("text") if last else None, last.at if last else None
            )
        )
    return items


async def get_conversation(
    s: AsyncSession, ctx: RequestContext, conversation_id: uuid.UUID, *, db: Database | None = None, lock: bool = False
) -> Conversation:
    q = select(Conversation).where(Conversation.id == conversation_id, Conversation.clinic_id == ctx.tenant)
    conv = await s.scalar(q.with_for_update() if lock else q)
    if conv is None:
        if db is not None:
            await audit.record_now(db, ctx, "access_denied", "conversation", conversation_id)
        raise Forbidden("conversation not found in this clinic", code="forbidden_or_not_found")
    return conv


async def reply(
    s: AsyncSession,
    ctx: RequestContext,
    clock: Clock,
    settings: Settings,
    conversation_id: uuid.UUID,
    text: str,
    *,
    db: Database | None = None,
) -> uuid.UUID:
    """FR-8.2: staff text lands in the patient's same WhatsApp chat. Free text needs the 24 h window (BR-9)."""
    conv = await get_conversation(s, ctx, conversation_id, db=db, lock=True)
    now = clock.now()
    if not messaging.in_window(conv, now):
        raise PolicyViolation(
            "the patient has not messaged in the last 24 hours; WhatsApp only allows approved templates — "
            "please call the patient",
            code="outside_24h_window",
        )
    clinic = await s.get(Clinic, ctx.tenant)
    count = await s.scalar(select(func.count()).where(Message.conversation_id == conv.id))
    outbox_id = await messaging.queue_message(
        s,
        clinic_id=ctx.tenant,
        to_phone=conv.phone,
        phone_number_id=messaging.sender_number(clinic, settings),
        category="transactional",
        key=f"staff:{conv.id}:{uuid.uuid4()}",
        run_at=now,
        session={"type": "text", "text": text},
        conversation_id=conv.id,
        sent_by_user_id=ctx.actor_id,
    )
    audit.record(s, ctx, "inbox.reply", "conversation", conv.id, after={"outbox_id": outbox_id, "seq": count})
    events.emit(s, events.clinic_channel(ctx.tenant), {"type": "inbox.updated", "conversation_id": conv.id})
    await s.commit()
    assert outbox_id is not None
    return outbox_id


async def hand_back(
    s: AsyncSession, ctx: RequestContext, clock: Clock, conversation_id: uuid.UUID, *, db: Database | None = None
) -> None:
    """FR-8.4: close the ticket and let the assistant answer again."""
    conv = await get_conversation(s, ctx, conversation_id, db=db, lock=True)
    ticket = await s.scalar(
        select(HandoverTicket).where(HandoverTicket.conversation_id == conv.id, HandoverTicket.status == "open")
    )
    if ticket is not None:
        ticket.status, ticket.closed_at, ticket.closed_by = "closed", clock.now(), ctx.actor_id
    conv.mode, conv.state = "assistant", {}
    audit.record(s, ctx, "inbox.hand_back", "conversation", conv.id)
    events.emit(s, events.clinic_channel(ctx.tenant), {"type": "inbox.updated", "conversation_id": conv.id})
    await s.commit()
