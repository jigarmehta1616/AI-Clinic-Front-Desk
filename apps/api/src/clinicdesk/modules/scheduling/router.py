from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from clinicdesk.core.context import RequestContext
from clinicdesk.core.deps import ClockDep, SessionDep, require
from clinicdesk.core.rbac import Permission
from clinicdesk.modules.scheduling import service
from clinicdesk.modules.scheduling.schemas import (
    DoctorCreate,
    DoctorOut,
    DoctorUpdate,
    ExceptionCreate,
    ExceptionOut,
    SessionOut,
    SessionsReplace,
    SlotOut,
)

router = APIRouter(tags=["scheduling"])
Manage = Annotated[RequestContext, Depends(require(Permission.DOCTOR_MANAGE))]
Read = Annotated[RequestContext, Depends(require(Permission.SCHEDULE_READ))]


def _doctor_out(d, sessions) -> DoctorOut:  # type: ignore[no-untyped-def]
    return DoctorOut(
        id=d.id,
        name=d.name,
        fee_paise=d.fee_paise,
        slot_minutes=d.slot_minutes,
        is_active=d.is_active,
        sessions=[SessionOut.model_validate(x, from_attributes=True) for x in sessions],
    )


@router.post("/doctors", response_model=DoctorOut, status_code=status.HTTP_201_CREATED)
async def create_doctor(body: DoctorCreate, s: SessionDep, ctx: Manage) -> DoctorOut:
    return _doctor_out(await service.create_doctor(s, ctx, body), [])


@router.get("/doctors", response_model=list[DoctorOut])
async def list_doctors(s: SessionDep, ctx: Read) -> list[DoctorOut]:
    return [_doctor_out(d, ss) for d, ss in await service.list_doctors(s, ctx)]


@router.patch("/doctors/{doctor_id}", response_model=DoctorOut)
async def update_doctor(doctor_id: uuid.UUID, body: DoctorUpdate, s: SessionDep, ctx: Manage) -> DoctorOut:
    return _doctor_out(await service.update_doctor(s, ctx, doctor_id, body), [])


@router.put("/doctors/{doctor_id}/sessions", response_model=list[SessionOut])
async def replace_sessions(doctor_id: uuid.UUID, body: SessionsReplace, s: SessionDep, ctx: Manage) -> list[SessionOut]:
    rows = await service.replace_sessions(s, ctx, doctor_id, body)
    return [SessionOut.model_validate(x, from_attributes=True) for x in rows]


@router.get("/doctors/{doctor_id}/slots", response_model=list[SlotOut])
async def available_slots(
    doctor_id: uuid.UUID,
    s: SessionDep,
    ctx: Read,
    clock: ClockDep,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
) -> list[SlotOut]:
    slots = await service.available_slots(s, ctx, clock, doctor_id, date_from, date_to, limit)
    return [SlotOut(start=x.start, end=x.end) for x in slots]


@router.post("/schedule-exceptions", response_model=ExceptionOut, status_code=status.HTTP_201_CREATED)
async def add_exception(body: ExceptionCreate, s: SessionDep, ctx: Manage, clock: ClockDep) -> ExceptionOut:
    exc, flagged = await service.add_exception(s, ctx, clock, body)
    out = ExceptionOut.model_validate(exc, from_attributes=True)
    out.flagged_appointments = flagged
    return out


@router.get("/schedule-exceptions", response_model=list[ExceptionOut])
async def list_exceptions(
    s: SessionDep, ctx: Read, date_from: Annotated[date, Query(alias="from")]
) -> list[ExceptionOut]:
    return [
        ExceptionOut.model_validate(x, from_attributes=True) for x in await service.list_exceptions(s, ctx, date_from)
    ]
