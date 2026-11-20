from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from clinicdesk.core.db import Base, IdMixin, TimestampMixin


class User(IdMixin, TimestampMixin, Base):
    """Global staff identity (platform table, no RLS). Patients are not users."""

    __tablename__ = "users"
    phone: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str | None] = mapped_column(String(120))
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Clinic(IdMixin, TimestampMixin, Base):
    """Tenant root (FR-1.1)."""

    __tablename__ = "clinics"
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(40), unique=True)  # clinic code for shared WA number (Q1)
    specialty: Mapped[str] = mapped_column(String(20))
    timezone: Mapped[str] = mapped_column(String(40), default="Asia/Kolkata", server_default="Asia/Kolkata")
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(5)), default=lambda: ["gu", "hi", "en"])
    address: Mapped[str | None] = mapped_column(String(500))
    map_url: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(16))
    wa_phone_number_id: Mapped[str | None] = mapped_column(String(32), unique=True)  # own number (FR-1.5)
    exotel_number: Mapped[str | None] = mapped_column(String(16), unique=True)  # virtual number (FR-3.1)
    plan: Mapped[str] = mapped_column(String(10), default="pilot", server_default="pilot")  # FR-9.1
    default_fee_paise: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), default="trial", server_default="trial")
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("specialty IN ('dental','physio')", name="specialty"),
        CheckConstraint("status IN ('trial','active','suspended')", name="status"),
        CheckConstraint("default_fee_paise >= 0", name="fee_nonneg"),
    )


class ClinicMembership(IdMixin, TimestampMixin, Base):
    __tablename__ = "clinic_memberships"
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clinics.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # set when role=doctor
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")

    __table_args__ = (
        UniqueConstraint("clinic_id", "user_id"),
        ForeignKeyConstraint(["clinic_id", "doctor_id"], ["doctors.clinic_id", "doctors.id"]),
        CheckConstraint("role IN ('owner','doctor','receptionist')", name="role"),
        CheckConstraint("status IN ('invited','active','disabled')", name="status"),
    )
