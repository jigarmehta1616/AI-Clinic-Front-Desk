from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from clinicdesk.core.context import RequestContext
from clinicdesk.core.deps import ClockDep, DbDep, SessionDep, require
from clinicdesk.core.rbac import Permission
from clinicdesk.modules.inbox import service
from clinicdesk.modules.messaging import service as messaging
from clinicdesk.modules.tenancy.schemas import Strict

router = APIRouter(prefix="/inbox", tags=["inbox"])
InboxCtx = Annotated[RequestContext, Depends(require(Permission.INBOX_HANDLE))]


class InboxItemOut(BaseModel):
    ticket_id: uuid.UUID
    conversation_id: uuid.UUID
    reason: str
    status: str
    opened_at: datetime
    phone: str
    patient_names: list[str]
    last_message: str | None
    last_at: datetime | None
    can_reply: bool


class MessageOut(BaseModel):
    id: uuid.UUID
    direction: str
    kind: str
    body: dict[str, Any]
    status: str | None
    sent_by_user_id: uuid.UUID | None
    at: datetime


class ReplyIn(Strict):
    text: str = Field(min_length=1, max_length=4000)


@router.get("", response_model=list[InboxItemOut])
async def list_inbox(
    s: SessionDep,
    ctx: InboxCtx,
    clock: ClockDep,
    status_: Annotated[Literal["open", "closed"], Query(alias="status")] = "open",
) -> list[InboxItemOut]:
    now = clock.now()
    return [
        InboxItemOut(
            ticket_id=i.ticket.id,
            conversation_id=i.conversation.id,
            reason=i.ticket.reason,
            status=i.ticket.status,
            opened_at=i.ticket.opened_at,
            phone=i.conversation.phone,
            patient_names=i.patient_names,
            last_message=i.last_message,
            last_at=i.last_at,
            can_reply=messaging.in_window(i.conversation, now),
        )
        for i in await service.list_open(s, ctx, status_)
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def conversation_messages(
    conversation_id: uuid.UUID,
    s: SessionDep,
    ctx: InboxCtx,
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[MessageOut]:
    conv = await service.get_conversation(s, ctx, conversation_id, db=db)
    return [
        MessageOut.model_validate(m, from_attributes=True) for m in await messaging.recent_messages(s, conv.id, limit)
    ]


@router.post("/conversations/{conversation_id}/reply", status_code=status.HTTP_202_ACCEPTED)
async def reply(
    conversation_id: uuid.UUID,
    body: ReplyIn,
    request: Request,
    s: SessionDep,
    ctx: InboxCtx,
    clock: ClockDep,
    db: DbDep,
) -> dict[str, str]:
    outbox_id = await service.reply(s, ctx, clock, request.app.state.settings, conversation_id, body.text, db=db)
    return {"outbox_id": str(outbox_id)}


@router.post("/conversations/{conversation_id}/hand-back", status_code=status.HTTP_204_NO_CONTENT)
async def hand_back(conversation_id: uuid.UUID, s: SessionDep, ctx: InboxCtx, clock: ClockDep, db: DbDep) -> None:
    await service.hand_back(s, ctx, clock, conversation_id, db=db)
