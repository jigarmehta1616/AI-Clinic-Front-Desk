from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from clinicdesk.core.db import Base, IdMixin, TimestampMixin

ACTIVE_STATUSES = ("booked", "confirmed", "arrived", "completed")
UPCOMING_STATUSES = ("booked", "confirmed")
ALL_STATUSES = (*ACTIVE_STATUSES, "cancelled", "rescheduled", "no_show")
SOURCES = ("assistant", "staff", "missed_call", "recall", "noshow_rebook")


class Appointment(IdMixin, TimestampMixin, Base):
    __tablename__ = "appointments"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    booked_by_phone: Mapped[str] = mapped_column(String(16))  # BR-4 counts per phone
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    slot_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12), default="booked")
    source: Mapped[str] = mapped_column(String(16))
    source_ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    rescheduled_from_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    visit_type: Mapped[str | None] = mapped_column(String(40))  # drives recall rules (FR-6.1)
    needs_reschedule: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "doctor_id"], ["doctors.clinic_id", "doctors.id"]),
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        CheckConstraint(f"status IN {ALL_STATUSES!r}", name="status"),
        CheckConstraint(f"source IN {SOURCES!r}", name="source"),
        CheckConstraint("slot_end > slot_start", name="slot_order"),
        # BR-1: one active booking per doctor slot — the database is the lock (ADR-0003).
        Index(
            "uq_appt_active_slot",
            "doctor_id",
            "slot_start",
            unique=True,
            postgresql_where=text(f"status IN {ACTIVE_STATUSES!r}"),
        ),
        Index("ix_appt_clinic_doctor_start", "clinic_id", "doctor_id", "slot_start"),
        Index("ix_appt_clinic_patient_start", "clinic_id", "patient_id", "slot_start"),
        Index("ix_appt_clinic_phone_doctor", "clinic_id", "booked_by_phone", "doctor_id"),
    )
