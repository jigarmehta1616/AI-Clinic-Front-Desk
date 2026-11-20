from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from clinicdesk.core.db import Base, IdMixin, TimestampMixin


class Patient(IdMixin, TimestampMixin, Base):
    """Minimal data per FRD §7: name, phone, age, language, family link. No clinical data."""

    __tablename__ = "patients"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clinics.id"))
    phone: Mapped[str] = mapped_column(String(16))  # WhatsApp number of the account holder
    name: Mapped[str] = mapped_column(String(120))
    age: Mapped[int | None] = mapped_column(SmallInteger)
    language: Mapped[str | None] = mapped_column(String(5))
    account_holder_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # family (FR-2.8)
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # FR-2.9

    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        UniqueConstraint("clinic_id", "phone", "name"),
        Index("ix_patients_clinic_phone", "clinic_id", "phone"),
        ForeignKeyConstraint(["clinic_id", "account_holder_id"], ["patients.clinic_id", "patients.id"]),
        CheckConstraint("age IS NULL OR age BETWEEN 0 AND 120", name="age"),
        CheckConstraint("language IS NULL OR language IN ('gu','hi','en')", name="language"),
    )


class ConsentEvent(IdMixin, TimestampMixin, Base):
    """Append-only consent history (DP-1, DP-2)."""

    __tablename__ = "consent_events"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    purpose: Mapped[str] = mapped_column(String(16))
    granted: Mapped[bool] = mapped_column(Boolean)
    channel: Mapped[str] = mapped_column(String(16))
    notice_version: Mapped[str] = mapped_column(String(20))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        CheckConstraint("purpose IN ('booking','reminders','recalls')", name="purpose"),
        CheckConstraint("channel IN ('whatsapp','dashboard','import')", name="channel"),
    )
