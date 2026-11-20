from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, status
from pydantic import BaseModel

from clinicdesk.core.context import RequestContext
from clinicdesk.core.deps import ClockDep, SessionDep, require
from clinicdesk.core.rbac import Permission
from clinicdesk.modules.patients import service as patients
from clinicdesk.modules.recall import revenue, service
from clinicdesk.modules.recall.service import FollowupIn, RuleIn

router = APIRouter(tags=["recall & revenue"])
RulesCtx = Annotated[RequestContext, Depends(require(Permission.RECALL_RULES_MANAGE))]
ReadCtx = Annotated[RequestContext, Depends(require(Permission.PATIENT_READ))]
StatusCtx = Annotated[RequestContext, Depends(require(Permission.APPOINTMENT_STATUS))]
ReportsCtx = Annotated[RequestContext, Depends(require(Permission.REPORTS_READ))]
VisitType = Annotated[str, Path(pattern=r"^[a-z_]{2,40}$")]


class RuleOut(BaseModel):
    id: uuid.UUID
    visit_type: str
    label: str
    delay_days: int
    followup_days: list[int]
    plan_based: bool
    is_active: bool


class RecallOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    plan_id: uuid.UUID | None
    visit_type: str | None
    label: str
    due_date: date
    status: str
    sends: int
    last_sent_at: datetime | None
    booked_appointment_id: uuid.UUID | None
    closed_reason: str | None
    patient_name: str | None = None
    patient_phone: str | None = None


@router.get("/recall/rules", response_model=list[RuleOut])
async def list_rules(s: SessionDep, ctx: ReadCtx) -> list[RuleOut]:
    return [RuleOut.model_validate(r, from_attributes=True) for r in await service.list_rules(s, ctx)]


@router.put("/recall/rules/{visit_type}", response_model=RuleOut)
async def upsert_rule(visit_type: VisitType, body: RuleIn, s: SessionDep, ctx: RulesCtx) -> RuleOut:
    """FR-6.1: owner edits trigger delay, follow-ups and plan behaviour per visit type."""
    return RuleOut.model_validate(await service.upsert_rule(s, ctx, visit_type, body), from_attributes=True)


@router.get("/recalls", response_model=list[RecallOut])
async def list_recalls(
    s: SessionDep,
    ctx: ReadCtx,
    status_: Annotated[
        Literal["scheduled", "sent", "booked", "declined", "lapsed", "cancelled", "skipped"] | None,
        Query(alias="status"),
    ] = None,
    patient_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[RecallOut]:
    rows = await service.list_recalls(s, ctx, status_, patient_id=patient_id)
    people = await patients.contacts(s, ctx, {r.patient_id for r in rows})
    out = []
    for r in rows:
        item = RecallOut.model_validate(r, from_attributes=True)
        p = people.get(r.patient_id)
        item.patient_name, item.patient_phone = (p.name, p.phone) if p else (None, None)
        out.append(item)
    return out


class FollowupOut(BaseModel):
    recall_id: uuid.UUID
    due_date: date
    label: str


class SourceTotals(BaseModel):
    visits: int
    estimated_revenue_paise: int


class RevenueItem(BaseModel):
    appointment_id: uuid.UUID
    source: str
    doctor: str
    fee_paise: int
    recovered_at: datetime


class RevenueReportOut(BaseModel):
    month: str
    currency: Literal["INR"]
    estimated: Literal[True]
    label: str
    total_visits: int
    total_estimated_revenue_paise: int
    by_source: dict[Literal["missed_call", "recall", "noshow_rebook"], SourceTotals]
    items: list[RevenueItem]


@router.post("/appointments/{appointment_id}/followup", status_code=status.HTTP_201_CREATED, response_model=FollowupOut)
async def set_followup(
    appointment_id: uuid.UUID, body: FollowupIn, s: SessionDep, ctx: StatusCtx, clock: ClockDep
) -> FollowupOut:
    """FR-6.2 one-tap follow-up after a visit."""
    return FollowupOut.model_validate(await service.set_followup(s, ctx, clock, appointment_id, body))


@router.get("/reports/revenue", response_model=RevenueReportOut)
async def revenue_report(
    s: SessionDep,
    ctx: ReportsCtx,
    clock: ClockDep,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> RevenueReportOut:
    """FR-7.3 / AC-11: recovered appointments by source and estimated revenue (always labelled estimated)."""
    from zoneinfo import ZoneInfo

    from clinicdesk.modules.tenancy.models import Clinic

    clinic = await s.get(Clinic, ctx.tenant)
    assert clinic is not None
    report = await revenue.monthly_report(
        s, ctx, month or revenue.current_month(clock.now(), ZoneInfo(clinic.timezone))
    )
    return RevenueReportOut.model_validate(report)
