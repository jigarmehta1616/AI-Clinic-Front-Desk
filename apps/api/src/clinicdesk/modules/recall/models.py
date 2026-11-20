from __future__ import annotations

import uuid
from datetime import date, datetime

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from clinicdesk.core.db import Base, IdMixin, TimestampMixin

RECALL_STATUSES = ("scheduled", "sent", "booked", "declined", "lapsed", "cancelled", "skipped")


class RecallRule(IdMixin, TimestampMixin, Base):
    """Clinic-defined rule per visit type (FR-6.1), seeded from a specialty template (FR-1.6)."""

    __tablename__ = "recall_rules"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clinics.id"))
    visit_type: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(80))
    delay_days: Mapped[int] = mapped_column(Integer)
    followup_days: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), default=lambda: [3, 7])
    plan_based: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    __table_args__ = (
        UniqueConstraint("clinic_id", "visit_type"),
        CheckConstraint("delay_days BETWEEN 1 AND 730", name="delay"),
        CheckConstraint("cardinality(followup_days) <= 2", name="max_two_followups"),  # FR-6.4
    )


class TreatmentPlan(IdMixin, TimestampMixin, Base):
    """'Plan: 10 sessions' (FR-6.2, FR-6.5)."""

    __tablename__ = "treatment_plans"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    visit_type: Mapped[str] = mapped_column(String(40))
    sessions_planned: Mapped[int] = mapped_column(SmallInteger)
    sessions_done: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    interval_days: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(10), default="active", server_default="active")

    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        ForeignKeyConstraint(["clinic_id", "doctor_id"], ["doctors.clinic_id", "doctors.id"]),
        CheckConstraint("sessions_planned BETWEEN 1 AND 100", name="planned"),
        CheckConstraint("sessions_done >= 0", name="done"),
        CheckConstraint("interval_days BETWEEN 1 AND 60", name="interval"),
        CheckConstraint("status IN ('active','completed','dropped','cancelled')", name="status"),
        # One active plan per patient and doctor: completions are counted against it.
        Index("uq_active_plan", "patient_id", "doctor_id", unique=True, postgresql_where=text("status = 'active'")),
    )


class Recall(IdMixin, TimestampMixin, Base):
    """A planned 'please come back' (FR-6.3/6.4). Lifecycle in recall/policy.py."""

    __tablename__ = "recalls"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_appointment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    visit_type: Mapped[str | None] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(80))
    due_date: Mapped[date] = mapped_column(Date)
    followup_days: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), default=lambda: [3, 7])
    status: Mapped[str] = mapped_column(String(10), default="scheduled", server_default="scheduled")
    sends: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    first_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    booked_appointment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    closed_reason: Mapped[str | None] = mapped_column(String(40))

    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        ForeignKeyConstraint(["clinic_id", "doctor_id"], ["doctors.clinic_id", "doctors.id"]),
        CheckConstraint(f"status IN {RECALL_STATUSES!r}", name="status"),
        CheckConstraint("sends BETWEEN 0 AND 3", name="sends"),
        Index("ix_recalls_clinic_status_due", "clinic_id", "status", "due_date"),
        # A completed visit creates at most one recall (idempotent hooks).
        Index(
            "uq_recall_source_appt",
            "source_appointment_id",
            unique=True,
            postgresql_where=text("source_appointment_id IS NOT NULL"),
        ),
    )


class RecoveryAttribution(IdMixin, TimestampMixin, Base):
    """Recovered visit (BR-11) with fee snapshot (BR-12). UNIQUE(appointment_id) prevents double counting."""

    __tablename__ = "recovery_attributions"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clinics.id"))
    appointment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(16))
    source_ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    fee_paise: Mapped[int] = mapped_column(Integer)
    recovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("source IN ('missed_call','recall','noshow_rebook')", name="source"),
        CheckConstraint("fee_paise >= 0", name="fee"),
        Index("ix_recovery_clinic_at", "clinic_id", "recovered_at"),
    )
