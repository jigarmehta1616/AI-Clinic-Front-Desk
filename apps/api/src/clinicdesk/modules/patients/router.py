from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from clinicdesk.core.context import RequestContext
from clinicdesk.core.deps import ClockDep, DbDep, SessionDep, require
from clinicdesk.core.rbac import Permission
from clinicdesk.modules.booking.schemas import AppointmentOut
from clinicdesk.modules.messaging.templates import NOTICE_VERSION
from clinicdesk.modules.patients import service
from clinicdesk.modules.patients.schemas import ConsentIn, PatientCreate, PatientOut, PatientUpdate

router = APIRouter(prefix="/patients", tags=["patients"])
ReadCtx = Annotated[RequestContext, Depends(require(Permission.PATIENT_READ))]
WriteCtx = Annotated[RequestContext, Depends(require(Permission.PATIENT_WRITE))]


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
async def create_patient(body: PatientCreate, s: SessionDep, ctx: WriteCtx) -> PatientOut:
    return PatientOut.model_validate(await service.create_patient(s, ctx, body), from_attributes=True)


@router.get("", response_model=list[PatientOut])
async def search_patients(
    s: SessionDep,
    ctx: ReadCtx,
    q: Annotated[str | None, Query(max_length=60)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[PatientOut]:
    return [PatientOut.model_validate(p, from_attributes=True) for p in await service.search(s, ctx, q, limit)]


@router.get("/{patient_id}/appointments", response_model=list[AppointmentOut])
async def patient_appointments(patient_id: uuid.UUID, s: SessionDep, ctx: ReadCtx, db: DbDep) -> list[AppointmentOut]:
    """FR-7.2: visit history + upcoming appointments for one patient."""
    from clinicdesk.modules.booking import service as booking

    patient = await service.get_patient(s, ctx, patient_id, db=db)
    rows = await booking.list_for_patient(s, ctx, patient.id)
    return [AppointmentOut.model_validate(a, from_attributes=True) for a in rows]


@router.get("/{patient_id}", response_model=PatientOut)
async def get_patient(patient_id: uuid.UUID, s: SessionDep, ctx: ReadCtx, db: DbDep) -> PatientOut:
    out = PatientOut.model_validate(await service.get_patient(s, ctx, patient_id, db=db), from_attributes=True)
    consents = await service.latest_consents(s, ctx, patient_id)
    out.reminders_consent, out.recalls_consent = consents.get("reminders"), consents.get("recalls")
    return out


@router.patch("/{patient_id}", response_model=PatientOut)
async def update_patient(patient_id: uuid.UUID, body: PatientUpdate, s: SessionDep, ctx: WriteCtx) -> PatientOut:
    return PatientOut.model_validate(await service.update_patient(s, ctx, patient_id, body), from_attributes=True)


@router.post("/{patient_id}/consents", status_code=status.HTTP_201_CREATED)
async def record_consent(
    patient_id: uuid.UUID, body: ConsentIn, s: SessionDep, ctx: WriteCtx, clock: ClockDep
) -> dict[str, str]:
    """DP-2: consent for reminders / recalls given at the desk (separate from booking consent)."""
    event = await service.record_consent(s, ctx, clock.now(), patient_id, body, NOTICE_VERSION)
    return {"consent_event_id": str(event.id)}
