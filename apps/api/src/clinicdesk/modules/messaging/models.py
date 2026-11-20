from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from clinicdesk.core.db import Base, IdMixin, TimestampMixin

CATEGORIES = ("transactional", "reminder", "recall", "promo")


class InboundEvent(IdMixin, TimestampMixin, Base):
    """Platform table: every provider webhook item, stored before acknowledging (NFR-4).

    UNIQUE(provider, external_id) deduplicates Meta's at-least-once deliveries.
    """

    __tablename__ = "inbound_events"
    provider: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(16))  # message | status
    phone_number_id: Mapped[str | None] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(12), default="received", server_default="received")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("uq_inbound_provider_external", "provider", "external_id", unique=True),
        CheckConstraint("status IN ('received','processed','ignored','failed')", name="status"),
    )


class Conversation(IdMixin, TimestampMixin, Base):
    """One WhatsApp thread per clinic and phone number."""

    __tablename__ = "conversations"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clinics.id"))
    phone: Mapped[str] = mapped_column(String(16))
    phone_number_id: Mapped[str | None] = mapped_column(String(32))  # our sending number
    language: Mapped[str | None] = mapped_column(String(5))
    mode: Mapped[str] = mapped_column(String(10), default="assistant", server_default="assistant")
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    consent_booking_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # DP-1
    consent_notice_version: Mapped[str | None] = mapped_column(String(20))
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # FR-2.9
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # BR-9 window
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("uq_conversations_clinic_phone", "clinic_id", "phone", unique=True),
        Index("uq_conversations_clinic_id", "clinic_id", "id", unique=True),
        CheckConstraint("mode IN ('assistant','staff')", name="mode"),
    )


class Message(IdMixin, Base):
    """Conversation log (FR-8.1). Retained 12 months then anonymised (DP-9).

    `seq` gives a total order: several messages can share a timestamp within one turn.
    """

    __tablename__ = "messages"
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    direction: Mapped[str] = mapped_column(String(3))
    kind: Mapped[str] = mapped_column(String(12))
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    provider_message_id: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str | None] = mapped_column(String(12))
    sent_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "conversation_id"], ["conversations.clinic_id", "conversations.id"]),
        CheckConstraint("direction IN ('in','out')", name="direction"),
        Index("ix_messages_conversation_at", "conversation_id", "at"),
        # Idempotent inbound processing: one row per provider message id.
        Index(
            "uq_messages_provider_id",
            "provider_message_id",
            unique=True,
            postgresql_where=sql_text("provider_message_id IS NOT NULL"),
        ),
    )


class OutboxMessage(IdMixin, TimestampMixin, Base):
    """Every outbound message (ADR-0004). Sent at most once per idempotency key."""

    __tablename__ = "outbox_messages"
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)  # send order per recipient
    clinic_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clinics.id"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    to_phone: Mapped[str] = mapped_column(String(16))
    phone_number_id: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(14))
    session_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    template: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    provider_message_id: Mapped[str | None] = mapped_column(String(160))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_status: Mapped[str | None] = mapped_column(String(12))
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint(f"category IN {CATEGORIES!r}", name="category"),
        CheckConstraint("status IN ('pending','sending','sent','failed','skipped','cancelled')", name="status"),
        CheckConstraint("session_payload IS NOT NULL OR template IS NOT NULL", name="has_content"),
        Index("ix_outbox_provider_id", "provider_message_id"),
    )


class HandoverTicket(IdMixin, TimestampMixin, Base):
    """Chat handed to staff (FR-8.1). At most one open ticket per conversation."""

    __tablename__ = "handover_tickets"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(8), default="open", server_default="open")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "conversation_id"], ["conversations.clinic_id", "conversations.id"]),
        CheckConstraint(
            "reason IN ('emergency','medical','complaint','unclear','requested','no_slots','other')", name="reason"
        ),
        CheckConstraint("status IN ('open','closed')", name="status"),
        Index(
            "uq_ticket_open_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=sql_text("status = 'open'"),
        ),
        Index("ix_tickets_clinic_status", "clinic_id", "status", "opened_at"),
    )
