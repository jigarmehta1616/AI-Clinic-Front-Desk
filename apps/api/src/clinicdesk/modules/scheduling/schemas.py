from __future__ import annotations

import uuid
from datetime import date, datetime, time
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from clinicdesk.modules.tenancy.schemas import Strict


class DoctorCreate(Strict):
    name: str = Field(min_length=2, max_length=120)
    fee_paise: int | None = Field(default=None, ge=0, le=10_000_000)
    slot_minutes: int = Field(default=15, ge=5, le=120)


class DoctorUpdate(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    fee_paise: int | None = Field(default=None, ge=0, le=10_000_000)
    slot_minutes: int | None = Field(default=None, ge=5, le=120)
    is_active: bool | None = None


class SessionIn(Strict):
    weekday: int = Field(ge=0, le=6, description="0 = Monday")
    start_time: time
    end_time: time
    max_tokens: int = Field(default=30, ge=0, le=500)

    @model_validator(mode="after")
    def _order(self) -> SessionIn:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class SessionsReplace(Strict):
    sessions: list[SessionIn] = Field(max_length=42)

    @model_validator(mode="after")
    def _no_overlap(self) -> SessionsReplace:
        by_day: dict[int, list[SessionIn]] = {}
        for s in self.sessions:
            by_day.setdefault(s.weekday, []).append(s)
        for items in by_day.values():
            items.sort(key=lambda s: s.start_time)
            for a, b in pairwise(items):
                if b.start_time < a.end_time:
                    raise ValueError("sessions on the same day overlap")
        return self


class SessionOut(BaseModel):
    id: uuid.UUID
    weekday: int
    start_time: time
    end_time: time
    max_tokens: int


class DoctorOut(BaseModel):
    id: uuid.UUID
    name: str
    fee_paise: int | None
    slot_minutes: int
    is_active: bool
    sessions: list[SessionOut] = []


class ExceptionCreate(Strict):
    doctor_id: uuid.UUID | None = None  # None = whole-clinic holiday
    start_date: date
    end_date: date
    kind: Literal["holiday", "leave"]
    reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check(self) -> ExceptionCreate:
        if self.end_date < self.start_date:
            raise ValueError("end_date before start_date")
        if (self.end_date - self.start_date).days > 90:
            raise ValueError("exception longer than 90 days")
        if self.kind == "leave" and self.doctor_id is None:
            raise ValueError("leave needs a doctor_id")
        return self


class ExceptionOut(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID | None
    start_date: date
    end_date: date
    kind: str
    reason: str | None
    flagged_appointments: int = 0


class SlotOut(BaseModel):
    start: datetime
    end: datetime
