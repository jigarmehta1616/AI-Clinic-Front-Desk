from __future__ import annotations

import uuid
from datetime import date, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from clinicdesk.core.db import Base, IdMixin, TimestampMixin


class Doctor(IdMixin, TimestampMixin, Base):
    __tablename__ = "doctors"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clinics.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    fee_paise: Mapped[int | None] = mapped_column(Integer)  # None → clinic default (Q5)
    slot_minutes: Mapped[int] = mapped_column(SmallInteger, default=15)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        CheckConstraint("slot_minutes BETWEEN 5 AND 120", name="slot_minutes"),
        CheckConstraint("fee_paise IS NULL OR fee_paise >= 0", name="fee_nonneg"),
    )


class DoctorSession(IdMixin, TimestampMixin, Base):
    """Weekly consulting block (FR-1.2), e.g. Mon 10:00–13:00. Times are clinic-local."""

    __tablename__ = "doctor_sessions"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    max_tokens: Mapped[int] = mapped_column(SmallInteger, default=30)

    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "doctor_id"], ["doctors.clinic_id", "doctors.id"], ondelete="CASCADE"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday"),
        CheckConstraint("end_time > start_time", name="time_order"),
        CheckConstraint("max_tokens BETWEEN 0 AND 500", name="max_tokens"),
    )


class ScheduleException(IdMixin, TimestampMixin, Base):
    """Holiday (doctor_id NULL = whole clinic) or doctor leave, whole days (FR-1.3)."""

    __tablename__ = "schedule_exceptions"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clinics.id"), index=True)
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "doctor_id"], ["doctors.clinic_id", "doctors.id"], ondelete="CASCADE"),
        CheckConstraint("end_date >= start_date", name="date_order"),
        CheckConstraint("kind IN ('holiday','leave')", name="kind"),
    )
