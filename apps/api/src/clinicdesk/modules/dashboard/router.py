from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from clinicdesk.core.context import RequestContext
from clinicdesk.core.deps import ClockDep, SessionDep, require
from clinicdesk.core.rbac import Permission
from clinicdesk.modules.dashboard import service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class AppointmentCounts(BaseModel):
    booked: int
    confirmed: int
    arrived: int
    completed: int
    no_show: int
    cancelled: int


class TokenCounts(BaseModel):
    waiting: int
    called: int
    skipped: int
    completed: int


class DoctorToday(BaseModel):
    doctor_id: uuid.UUID
    name: str
    is_active: bool
    appointments: AppointmentCounts
    tokens: TokenCounts
    current_token: int | None


class TodayOut(BaseModel):
    day: date
    doctors: list[DoctorToday]
    open_chats: int
    emergencies: int
    needs_reschedule: int
    recalls_due: int
    missed_calls_today: int
    call_backs_needed: int


@router.get("/today", response_model=TodayOut)
async def today(
    s: SessionDep,
    ctx: Annotated[RequestContext, Depends(require(Permission.APPOINTMENT_READ))],
    clock: ClockDep,
    day: Annotated[date, Query()],
) -> TodayOut:
    """FR-7.1: appointments, tokens, arrivals, no-shows per doctor, open chats (doctors: own row only)."""
    return TodayOut.model_validate(await service.today(s, ctx, day, clock.now()))
