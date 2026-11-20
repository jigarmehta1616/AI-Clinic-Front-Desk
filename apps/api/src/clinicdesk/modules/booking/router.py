from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from clinicdesk.core.context import RequestContext
from clinicdesk.core.deps import ClockDep, DbDep, SessionDep, require
from clinicdesk.core.rbac import Permission
from clinicdesk.modules.booking import service
from clinicdesk.modules.booking.schemas import AppointmentOut, BookIn, CancelIn, RescheduleIn, StatusIn
from clinicdesk.modules.patients import service as patients

router = APIRouter(prefix="/appointments", tags=["appointments"])
BookCtx = Annotated[RequestContext, Depends(require(Permission.APPOINTMENT_BOOK))]
StatusCtx = Annotated[RequestContext, Depends(require(Permission.APPOINTMENT_STATUS))]
ReadCtx = Annotated[RequestContext, Depends(require(Permission.APPOINTMENT_READ))]


def _out(a) -> AppointmentOut:  # type: ignore[no-untyped-def]
    return AppointmentOut.model_validate(a, from_attributes=True)


async def _with_names(s, ctx, appts) -> list[AppointmentOut]:  # type: ignore[no-untyped-def]
    people = await patients.contacts(s, ctx, {a.patient_id for a in appts})
    out = []
    for a in appts:
        row = _out(a)
        p = people.get(a.patient_id)
        row.patient_name, row.patient_phone = (p.name, p.phone) if p else (None, None)
        out.append(row)
    return out


@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def book(body: BookIn, s: SessionDep, ctx: BookCtx, clock: ClockDep) -> AppointmentOut:
    return _out(await service.book(s, ctx, clock, body))


@router.get("", response_model=list[AppointmentOut])
async def list_for_day(
    s: SessionDep,
    ctx: ReadCtx,
    day: Annotated[date, Query()],
    doctor_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[AppointmentOut]:
    return await _with_names(s, ctx, await service.list_for_day(s, ctx, day, doctor_id))


@router.post("/{appointment_id}/reschedule", response_model=AppointmentOut)
async def reschedule(
    appointment_id: uuid.UUID, body: RescheduleIn, s: SessionDep, ctx: BookCtx, clock: ClockDep, db: DbDep
) -> AppointmentOut:
    return _out(await service.reschedule(s, ctx, clock, appointment_id, body, db=db))


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel(
    appointment_id: uuid.UUID, body: CancelIn, s: SessionDep, ctx: BookCtx, clock: ClockDep, db: DbDep
) -> AppointmentOut:
    return _out(await service.cancel(s, ctx, clock, appointment_id, body, db=db))


@router.post("/{appointment_id}/status", response_model=AppointmentOut)
async def set_status(
    appointment_id: uuid.UUID, body: StatusIn, s: SessionDep, ctx: StatusCtx, clock: ClockDep, db: DbDep
) -> AppointmentOut:
    return _out(await service.set_status(s, ctx, clock, appointment_id, body.status, db=db))
