from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from clinicdesk.core.db import Base, IdMixin


class AuditLog(IdMixin, Base):
    """Append-only (BR-13, DP-10). Runtime role has no UPDATE/DELETE grant on this table."""

    __tablename__ = "audit_log"
    clinic_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_type: Mapped[str] = mapped_column(String(12))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    channel: Mapped[str] = mapped_column(String(12))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    request_id: Mapped[str | None] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("actor_type IN ('user','patient','system','assistant','anonymous')", name="actor_type"),
        CheckConstraint("channel IN ('dashboard','whatsapp','system','api')", name="channel"),
        Index("ix_audit_clinic_at", "clinic_id", "at"),
        Index("ix_audit_entity", "clinic_id", "entity_type", "entity_id"),
        # No INSERT ... RETURNING: Postgres would check RETURNING rows against the SELECT policy,
        # and platform-level rows (clinic_id NULL) are deliberately unreadable to tenants.
        {"implicit_returning": False},
    )
    __mapper_args__ = {"eager_defaults": False}
