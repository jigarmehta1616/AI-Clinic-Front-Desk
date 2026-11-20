from __future__ import annotations

import hmac
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy.dialects.postgresql import insert

from clinicdesk.core.context import RequestContext
from clinicdesk.core.deps import ClockDep, SessionDep, require
from clinicdesk.core.errors import NotFound
from clinicdesk.core.logging import log
from clinicdesk.core.rbac import Permission
from clinicdesk.modules.calls import service
from clinicdesk.modules.jobs import service as jobs
from clinicdesk.modules.messaging.models import InboundEvent
from clinicdesk.modules.patients import service as patients
from clinicdesk.modules.tenancy.schemas import Strict, normalize_phone

router = APIRouter(tags=["missed calls"])
CallsCtx = Annotated[RequestContext, Depends(require(Permission.CALLS_HANDLE))]
StatusQ = Literal["pending", "recovered", "call_back_needed", "resolved"]


class MissedCallOut(BaseModel):
    id: uuid.UUID
    caller_phone: str
    called_at: datetime
    last_called_at: datetime
    repeat_count: int
    status: str
    source: str
    offer_sent_at: datetime | None
    appointment_id: uuid.UUID | None
    resolution: str | None
    patient_name: str | None = None
    patient_id: uuid.UUID | None = None


class ManualCallIn(Strict):
    phone: str

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)


class ResolveIn(Strict):
    outcome: Literal["called_back", "booked_by_phone", "no_answer", "not_needed"]


@router.get("/missed-calls", response_model=list[MissedCallOut])
async def list_calls(
    s: SessionDep,
    ctx: CallsCtx,
    day: Annotated[date | None, Query()] = None,
    status_: Annotated[StatusQ | None, Query(alias="status")] = None,
) -> list[MissedCallOut]:
    """FR-3.4: missed calls with status recovered / pending / call back needed."""
    rows = await service.list_calls(s, ctx, day, status_)
    known = await patients.by_phones(s, ctx, {r.caller_phone for r in rows})
    out = []
    for r in rows:
        item = MissedCallOut.model_validate(r, from_attributes=True)
        p = known.get(r.caller_phone)
        if p is not None:
            item.patient_name, item.patient_id = p.name, p.id
        out.append(item)
    return out


@router.post("/missed-calls", response_model=MissedCallOut, status_code=status.HTTP_201_CREATED)
async def add_manual(body: ManualCallIn, s: SessionDep, ctx: CallsCtx, clock: ClockDep) -> MissedCallOut:
    return MissedCallOut.model_validate(await service.add_manual(s, ctx, body.phone, clock.now()), from_attributes=True)


@router.post("/missed-calls/{call_id}/resolve", response_model=MissedCallOut)
async def resolve(call_id: uuid.UUID, body: ResolveIn, s: SessionDep, ctx: CallsCtx) -> MissedCallOut:
    return MissedCallOut.model_validate(await service.resolve(s, ctx, call_id, body.outcome), from_attributes=True)


@router.api_route("/webhooks/exotel/{token}", methods=["GET", "POST"], include_in_schema=False)
async def exotel_webhook(token: str, request: Request) -> Response:
    """FR-3.1: Exotel Passthru / status callback. Exotel does not sign requests, so the URL carries a secret
    (plus an IP allowlist at Nginx). Persist-then-ack; processing happens in the `exotel.inbound` job."""
    rt = request.app.state.runtime
    secret = rt.settings.exotel_webhook_secret
    if not secret or not hmac.compare_digest(token, secret):
        raise NotFound("not found")
    params = dict(request.query_params)
    if request.method == "POST":
        form = await request.form()
        params.update({k: str(v) for k, v in form.items()})
    sid = (params.get("CallSid") or "").strip()[:64]
    if not sid:
        return Response(status_code=200)
    async with rt.db.session(bypass_rls=True) as s:
        event_id = await s.scalar(
            insert(InboundEvent)
            .values(provider="exotel", external_id=sid, kind="call", phone_number_id=None, payload=params)
            .on_conflict_do_nothing(index_elements=["provider", "external_id"])
            .returning(InboundEvent.id)
        )
        if event_id is not None:
            await jobs.enqueue(
                s,
                clinic_id=None,
                kind="exotel.inbound",
                run_at=rt.clock.now(),
                dedup_key=f"exotel.inbound:{event_id}",
                payload={"event_id": str(event_id)},
            )
        await s.commit()
        await jobs.flush_wakes(s, rt.waker)
    log.info("exotel_webhook", new=event_id is not None)
    return Response(status_code=200)
