from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from clinicdesk.modules.tenancy.schemas import Strict, normalize_phone


class PatientCreate(Strict):
    phone: str
    name: str = Field(min_length=1, max_length=120)
    age: int | None = Field(default=None, ge=0, le=120)
    language: Literal["gu", "hi", "en"] | None = None
    account_holder_id: uuid.UUID | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)


class PatientUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    age: int | None = Field(default=None, ge=0, le=120)
    language: Literal["gu", "hi", "en"] | None = None


class PatientOut(BaseModel):
    id: uuid.UUID
    phone: str
    name: str
    age: int | None
    language: str | None
    account_holder_id: uuid.UUID | None
    opted_out_at: datetime | None
    created_at: datetime
    # Latest consent per purpose (DP-2); filled on the detail endpoint only. None = never asked.
    reminders_consent: bool | None = None
    recalls_consent: bool | None = None


class ConsentIn(Strict):
    purpose: Literal["reminders", "recalls"]
    granted: bool
