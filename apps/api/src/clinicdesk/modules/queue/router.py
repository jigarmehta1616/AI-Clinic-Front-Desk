from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, field_validator

from clinicdesk.core.context import RequestContext
from clinicdesk.core.deps import ClockDep, DbDep, SessionDep, require
from clinicdesk.core.errors import NotFound
from clinicdesk.core.rbac import Permission
from clinicdesk.modules.patients import service as patients
from clinicdesk.modules.queue import service
from clinicdesk.modules.tenancy.schemas import Strict, normalize_phone

router = APIRouter(prefix="/queue", tags=["queue"])
public_router = APIRouter(prefix="/public", tags=["public"])
IssueCtx = Annotated[RequestContext, Depends(require(Permission.QUEUE_ISSUE))]
OperateCtx = Annotated[RequestContext, Depends(require(Permission.QUEUE_OPERATE))]
ReadCtx = Annotated[RequestContext, Depends(require(Permission.SCHEDULE_READ))]


class TokenIn(Strict):
    doctor_id: uuid.UUID
    patient_id: uuid.UUID | None = None
    phone: str | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else v


class EntryOut(BaseModel):
    id: uuid.UUID
    queue_session_id: uuid.UUID
    token_no: int
    kind: str
    status: str
    patient_id: uuid.UUID | None
    appointment_id: uuid.UUID | None
    slot_start: datetime | None
    issued_at: datetime
    called_at: datetime | None
    public_code: str
    patient_name: str | None = None  # staff view only; never on public routes
    phone: str | None = None
    ahead: int | None = None
    eta: datetime | None = None


class QueueSessionOut(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    session_date: date
    starts_at: datetime
    ends_at: datetime
    max_tokens: int
    current_token_no: int | None
    avg_consult_minutes: float
    entries: list[EntryOut]


def _entry(e, ahead=None, eta=None) -> EntryOut:  # type: ignore[no-untyped-def]
    out = EntryOut.model_validate(e, from_attributes=True)
    out.ahead, out.eta = ahead, eta
    return out


@router.post("/tokens", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
async def issue_token(body: TokenIn, s: SessionDep, ctx: IssueCtx, clock: ClockDep) -> EntryOut:
    """FR-4.1 receptionist issues a walk-in token."""
    e = await service.issue_token(
        s,
        ctx,
        clock,
        doctor_id=body.doctor_id,
        patient_id=body.patient_id,
        phone=body.phone,
        channel="dashboard",
    )
    return _entry(e)


@router.get("", response_model=list[QueueSessionOut])
async def get_queue(
    s: SessionDep,
    ctx: ReadCtx,
    clock: ClockDep,
    doctor_id: Annotated[uuid.UUID, Query()],
    day: Annotated[date, Query()],
) -> list[QueueSessionOut]:
    snaps = await service.snapshot_for(s, ctx, clock, doctor_id, day)
    people = await patients.contacts(
        s, ctx, {v.entry.patient_id for sn in snaps for v in sn.entries if v.entry.patient_id}
    )

    def staff_entry(v: service.EntryView) -> EntryOut:
        out = _entry(v.entry, v.ahead, v.eta)
        p = people.get(v.entry.patient_id) if v.entry.patient_id else None
        out.patient_name, out.phone = (p.name if p else None), (p.phone if p else v.entry.phone)
        return out

    return [
        QueueSessionOut(
            id=sn.session.id,
            doctor_id=sn.session.doctor_id,
            session_date=sn.session.session_date,
            starts_at=sn.session.starts_at,
            ends_at=sn.session.ends_at,
            max_tokens=sn.session.max_tokens,
            current_token_no=sn.current.token_no if sn.current else None,
            avg_consult_minutes=round(sn.avg_consult.total_seconds() / 60, 1),
            entries=[staff_entry(v) for v in sn.entries],
        )
        for sn in snaps
    ]


@router.post("/sessions/{queue_session_id}/next", response_model=EntryOut | None)
async def call_next(queue_session_id: uuid.UUID, s: SessionDep, ctx: OperateCtx, clock: ClockDep) -> EntryOut | None:
    e = await service.call_next(s, ctx, clock, queue_session_id)
    return _entry(e) if e else None


@router.post("/sessions/{queue_session_id}/complete-current", status_code=status.HTTP_204_NO_CONTENT)
async def complete_current(queue_session_id: uuid.UUID, s: SessionDep, ctx: OperateCtx, clock: ClockDep) -> None:
    await service.complete_current(s, ctx, clock, queue_session_id)


@router.post("/entries/{entry_id}/{action}", response_model=EntryOut)
async def change_entry(
    entry_id: uuid.UUID,
    action: Literal["skip", "recall", "cancel"],
    s: SessionDep,
    ctx: OperateCtx,
    clock: ClockDep,
    db: DbDep,
) -> EntryOut:
    return _entry(await service.change_entry(s, ctx, clock, entry_id, action, db=db))


class PublicQueueOut(BaseModel):
    token_no: int
    status: str
    current_token_no: int | None
    ahead: int | None
    eta: datetime | None
    doctor_name: str


@public_router.get("/queue/{code}", response_model=PublicQueueOut)
async def public_queue(code: str, db: DbDep, clock: ClockDep) -> PublicQueueOut:
    """FR-4.2: patient's live token status. No names or phones of anyone."""
    if not (16 <= len(code) <= 32) or not code.replace("-", "").replace("_", "").isalnum():
        raise NotFound("unknown token link")
    st = await service.public_status(db, clock, code)
    if st is None:
        raise NotFound("unknown token link")
    return PublicQueueOut(**asdict(st))
