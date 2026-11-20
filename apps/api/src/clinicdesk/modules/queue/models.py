from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from clinicdesk.core.db import Base, IdMixin, TimestampMixin

ENTRY_STATUSES = ("waiting", "called", "skipped", "completed", "cancelled")


class QueueSession(IdMixin, TimestampMixin, Base):
    """One doctor session on one date (e.g. Dr. Shah, Mon 23 Nov, 10:00–13:00).

    The row is the lock for token numbering and the BR-5 token limit; `current_entry_id` is who is
    with the doctor now.
    """

    __tablename__ = "queue_sessions"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clinics.id"))
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    session_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_tokens: Mapped[int] = mapped_column(SmallInteger)
    last_token_no: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    current_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        UniqueConstraint("doctor_id", "session_date", "start_time"),
        ForeignKeyConstraint(["clinic_id", "doctor_id"], ["doctors.clinic_id", "doctors.id"]),
        Index("ix_queue_sessions_clinic_date", "clinic_id", "session_date"),
    )


class QueueEntry(IdMixin, TimestampMixin, Base):
    """A token in a session queue: walk-in, or a booked patient who has arrived (FR-4.6)."""

    __tablename__ = "queue_entries"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    queue_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    token_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(10), default="waiting")
    priority: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    phone: Mapped[str | None] = mapped_column(String(16))  # for "N ahead" alerts (FR-4.3)
    slot_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str] = mapped_column(String(10))
    public_code: Mapped[str] = mapped_column(String(32), unique=True)  # unguessable tracking link (FR-4.2)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("queue_session_id", "token_no"),
        ForeignKeyConstraint(["clinic_id", "queue_session_id"], ["queue_sessions.clinic_id", "queue_sessions.id"]),
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        CheckConstraint("kind IN ('booked','walk_in')", name="kind"),
        CheckConstraint(f"status IN {ENTRY_STATUSES!r}", name="status"),
        CheckConstraint("channel IN ('dashboard','qr','whatsapp')", name="channel"),
        CheckConstraint("(kind = 'booked') = (appointment_id IS NOT NULL)", name="booked_has_appt"),
        # A booked appointment can enter the queue at most once.
        Index("uq_queue_entries_appointment", "appointment_id", unique=True),
        Index("ix_queue_entries_session_status", "queue_session_id", "status"),
    )
