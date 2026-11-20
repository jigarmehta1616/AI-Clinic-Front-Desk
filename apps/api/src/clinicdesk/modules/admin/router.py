from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from clinicdesk.core.context import RequestContext
from clinicdesk.core.deps import ClockDep, DbDep, PrincipalDep, SessionDep, require
from clinicdesk.core.errors import Forbidden
from clinicdesk.core.rbac import Permission
from clinicdesk.modules.admin import service
from clinicdesk.modules.tenancy.schemas import Strict

router = APIRouter(tags=["plan & platform admin"])


class UsageOut(BaseModel):
    plan: str
    status: str
    trial_ends_at: datetime | None
    days_left: int | None
    messages_this_month: int
    messages_limit: int | None
    messages_level: Literal["ok", "warning", "exceeded"]
    doctors: int
    doctors_limit: int | None
    doctors_level: Literal["ok", "warning", "exceeded"]
    patients: int


class AdminClinicOut(UsageOut):
    id: uuid.UUID
    name: str = ""
    slug: str = ""
    specialty: str = ""
    created_at: datetime | None = None


class ExtendIn(Strict):
    days: int = Field(ge=1, le=365)


class PlanIn(Strict):
    plan: Literal["pilot", "basic", "pro"]


class SuspendIn(Strict):
    reason: str = Field(min_length=3, max_length=200)


async def platform_admin(ctx: PrincipalDep) -> RequestContext:
    if not ctx.is_platform_admin:
        raise Forbidden("platform admins only", code="not_platform_admin")
    return ctx


AdminCtx = Annotated[RequestContext, Depends(platform_admin)]


@router.get("/clinic/usage", response_model=UsageOut)
async def clinic_usage(
    s: SessionDep, ctx: Annotated[RequestContext, Depends(require(Permission.CLINIC_READ))], clock: ClockDep
) -> UsageOut:
    """FR-9.1 days left + usage; FR-9.3 warning levels."""
    return UsageOut.model_validate(await service.usage(s, ctx, clock.now()))


@router.get("/admin/clinics", response_model=list[AdminClinicOut])
async def admin_clinics(ctx: AdminCtx, db: DbDep, clock: ClockDep) -> list[AdminClinicOut]:
    """FR-9.4: every clinic with plan, trial and usage counts (no patient data, DP-10)."""
    return [AdminClinicOut.model_validate(c) for c in await service.list_clinics(db, clock.now())]


@router.post("/admin/clinics/{clinic_id}/extend-trial", response_model=AdminClinicOut)
async def extend_trial(
    clinic_id: uuid.UUID, body: ExtendIn, ctx: AdminCtx, db: DbDep, clock: ClockDep
) -> AdminClinicOut:
    return AdminClinicOut.model_validate(
        await service.change_clinic(db, ctx, clinic_id, clock.now(), action="extend_trial", value=body.days)
    )


@router.post("/admin/clinics/{clinic_id}/plan", response_model=AdminClinicOut)
async def change_plan(clinic_id: uuid.UUID, body: PlanIn, ctx: AdminCtx, db: DbDep, clock: ClockDep) -> AdminClinicOut:
    return AdminClinicOut.model_validate(
        await service.change_clinic(db, ctx, clinic_id, clock.now(), action="plan", value=body.plan)
    )


@router.post("/admin/clinics/{clinic_id}/suspend", response_model=AdminClinicOut)
async def suspend(clinic_id: uuid.UUID, body: SuspendIn, ctx: AdminCtx, db: DbDep, clock: ClockDep) -> AdminClinicOut:
    return AdminClinicOut.model_validate(
        await service.change_clinic(db, ctx, clinic_id, clock.now(), action="suspend", value=body.reason)
    )


@router.post("/admin/clinics/{clinic_id}/reactivate", response_model=AdminClinicOut)
async def reactivate(clinic_id: uuid.UUID, ctx: AdminCtx, db: DbDep, clock: ClockDep) -> AdminClinicOut:
    return AdminClinicOut.model_validate(
        await service.change_clinic(db, ctx, clinic_id, clock.now(), action="reactivate")
    )
