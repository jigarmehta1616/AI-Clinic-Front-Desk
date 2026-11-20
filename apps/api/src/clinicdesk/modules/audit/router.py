from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from clinicdesk.core.context import RequestContext
from clinicdesk.core.deps import SessionDep, require
from clinicdesk.core.rbac import Permission
from clinicdesk.modules.audit import service

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditOut(BaseModel):
    id: uuid.UUID
    actor_type: str
    actor_id: uuid.UUID | None
    channel: str
    action: str
    entity_type: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    at: datetime


@router.get("", response_model=list[AuditOut])
async def list_audit(
    s: SessionDep,
    ctx: Annotated[RequestContext, Depends(require(Permission.AUDIT_READ))],
    entity_type: Annotated[str | None, Query(max_length=40)] = None,
    entity_id: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditOut]:
    rows = await service.list_for_entity(s, entity_type, entity_id, limit)
    return [AuditOut.model_validate(r, from_attributes=True) for r in rows]
