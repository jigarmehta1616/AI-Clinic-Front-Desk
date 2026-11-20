from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from clinicdesk.core.context import RequestContext
from clinicdesk.core.deps import ClockDep, DbDep, PrincipalDep, SessionDep, SettingsDep, require
from clinicdesk.core.rbac import Permission
from clinicdesk.modules.auth import service as auth_service
from clinicdesk.modules.auth.router import _respond
from clinicdesk.modules.auth.schemas import TokenResponse
from clinicdesk.modules.tenancy import service
from clinicdesk.modules.tenancy.schemas import (
    ClinicCreate,
    ClinicOut,
    ClinicUpdate,
    MembershipOut,
    StaffInvite,
)

router = APIRouter(tags=["clinic"])


class OnboardingOut(BaseModel):
    clinic: ClinicOut
    tokens: TokenResponse


@router.post("/clinics", response_model=OnboardingOut, status_code=status.HTTP_201_CREATED)
async def create_clinic(
    body: ClinicCreate,
    ctx: PrincipalDep,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> OnboardingOut:
    """FR-1.1: a signed-in user creates a clinic and becomes its owner."""
    clinic = await service.create_clinic(db, clock, ctx, body)
    tokens = await auth_service.issue_for_membership(db, settings, clock, ctx.actor_id, clinic.id)  # type: ignore[arg-type]
    return OnboardingOut(clinic=service.to_out(clinic), tokens=_respond(response, settings, tokens))


@router.get("/clinic", response_model=ClinicOut)
async def get_clinic(
    s: SessionDep, ctx: Annotated[RequestContext, Depends(require(Permission.CLINIC_READ))]
) -> ClinicOut:
    return service.to_out(await service.get_clinic(s, ctx))


@router.patch("/clinic", response_model=ClinicOut)
async def update_clinic(
    body: ClinicUpdate,
    s: SessionDep,
    ctx: Annotated[RequestContext, Depends(require(Permission.CLINIC_MANAGE))],
) -> ClinicOut:
    return service.to_out(await service.update_clinic(s, ctx, body))


class StaffOut(MembershipOut):
    phone: str
    name: str | None


@router.post("/clinic/staff", response_model=MembershipOut, status_code=status.HTTP_201_CREATED)
async def invite_staff(
    body: StaffInvite,
    s: SessionDep,
    ctx: Annotated[RequestContext, Depends(require(Permission.STAFF_MANAGE))],
) -> MembershipOut:
    m = await service.invite_staff(s, ctx, body)
    return MembershipOut.model_validate(m, from_attributes=True)


@router.get("/clinic/staff", response_model=list[StaffOut])
async def list_staff(
    s: SessionDep, ctx: Annotated[RequestContext, Depends(require(Permission.STAFF_MANAGE))]
) -> list[StaffOut]:
    return [
        StaffOut(
            id=m.id,
            clinic_id=m.clinic_id,
            user_id=m.user_id,
            role=m.role,
            doctor_id=m.doctor_id,
            status=m.status,
            phone=u.phone,
            name=u.name,
        )
        for m, u in await service.list_staff(s, ctx)
    ]
