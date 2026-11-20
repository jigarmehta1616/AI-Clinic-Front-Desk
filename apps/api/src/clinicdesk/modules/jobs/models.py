from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from clinicdesk.core.db import Base, IdMixin, TimestampMixin


class ScheduledJob(IdMixin, TimestampMixin, Base):
    """Durable unit of deferred work (ADR-0004, NFR-5). `dedup_key` makes enqueueing idempotent."""

    __tablename__ = "scheduled_jobs"
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)  # creation order (tie-breaker)
    clinic_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clinics.id"))
    kind: Mapped[str] = mapped_column(String(40))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    dedup_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(SmallInteger, default=6, server_default="6")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("status IN ('pending','running','done','failed','cancelled')", name="status"),
        Index("ix_jobs_due", "run_at", postgresql_where=text("status = 'pending'")),
        Index("ix_jobs_running", "locked_at", postgresql_where=text("status = 'running'")),
    )
