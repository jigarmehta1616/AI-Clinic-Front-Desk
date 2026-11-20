"""Audit trail (BR-13, DP-10). `record` joins the caller's transaction; `record_now` commits on its own
so that denied requests are logged even though the request itself fails (AC-10)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core.context import RequestContext
from clinicdesk.core.db import Database
from clinicdesk.modules.audit.models import AuditLog


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def record(
    session: AsyncSession,
    ctx: RequestContext,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str | None,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    clinic_id: uuid.UUID | None = None,
) -> None:
    session.add(
        AuditLog(
            clinic_id=clinic_id if clinic_id is not None else ctx.clinic_id,
            actor_type=ctx.actor_type,
            actor_id=ctx.actor_id,
            channel=ctx.channel,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            before=_jsonable(before) if before else None,
            after=_jsonable(after) if after else None,
            request_id=ctx.request_id,
        )
    )


async def record_now(db: Database, ctx: RequestContext, action: str, entity_type: str, entity_id: Any) -> None:
    async with db.session(clinic_id=ctx.clinic_id, user_id=ctx.actor_id) as s:
        record(s, ctx, action, entity_type, entity_id)
        await s.commit()


async def list_for_entity(
    session: AsyncSession, entity_type: str | None, entity_id: str | None, limit: int = 100
) -> list[AuditLog]:
    q = select(AuditLog).order_by(AuditLog.at.desc()).limit(limit)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    return list((await session.scalars(q)).all())
