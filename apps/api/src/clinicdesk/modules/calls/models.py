from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from clinicdesk.core.db import Base, IdMixin, TimestampMixin

STATUSES = ("pending", "recovered", "call_back_needed", "resolved")


class MissedCall(IdMixin, TimestampMixin, Base):
    """An unanswered call forwarded to the clinic's Exotel number (FR-3.1). One row per 30-minute burst (FR-3.5)."""

    __tablename__ = "missed_calls"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clinics.id"))
    caller_phone: Mapped[str] = mapped_column(String(16))
    first_call_sid: Mapped[str | None] = mapped_column(String(64))
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    repeat_count: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    source: Mapped[str] = mapped_column(String(10), default="exotel", server_default="exotel")
    offer_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    resolution: Mapped[str | None] = mapped_column(String(20))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint(f"status IN {STATUSES!r}", name="status"),
        CheckConstraint("source IN ('exotel','manual')", name="source"),
        Index("ix_missed_calls_clinic_called", "clinic_id", "called_at"),
        Index("ix_missed_calls_clinic_phone", "clinic_id", "caller_phone", "last_called_at"),
    )
