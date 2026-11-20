from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from clinicdesk.modules.tenancy.schemas import Strict


class BookIn(Strict):
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    slot_start: AwareDatetime
    source: Literal["staff", "missed_call", "recall", "noshow_rebook"] = "staff"
    source_ref_id: uuid.UUID | None = None
    visit_type: str | None = Field(default=None, pattern=r"^[a-z_]{2,40}$")


class RescheduleIn(Strict):
    slot_start: AwareDatetime
    doctor_id: uuid.UUID | None = None  # default: same doctor


class CancelIn(Strict):
    reason: str | None = Field(default=None, max_length=200)
    staff_override: bool = False


class StatusIn(Strict):
    status: Literal["confirmed", "arrived", "completed", "no_show"]


class AppointmentOut(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    slot_start: datetime
    slot_end: datetime
    status: str
    source: str
    source_ref_id: uuid.UUID | None
    rescheduled_from_id: uuid.UUID | None
    visit_type: str | None = None
    needs_reschedule: bool
    arrived_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    patient_name: str | None = None  # staff list views only
    patient_phone: str | None = None


class AppointmentQuery(Strict):
    day: date
    doctor_id: uuid.UUID | None = None
