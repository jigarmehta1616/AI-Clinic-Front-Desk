from __future__ import annotations

import re
import uuid
from datetime import datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

E164 = re.compile(r"^\+[1-9]\d{7,14}$")

_ALL_LANGUAGES: tuple[Literal["gu", "hi", "en"], ...] = ("gu", "hi", "en")


def normalize_phone(value: str) -> str:
    """Normalise to E.164; bare 10-digit Indian mobiles get +91."""
    v = re.sub(r"[\s()-]", "", value)
    if re.fullmatch(r"[6-9]\d{9}", v):
        v = "+91" + v
    elif re.fullmatch(r"91[6-9]\d{9}", v):
        v = "+" + v
    if not E164.match(v):
        raise ValueError("invalid phone number")
    return v


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClinicSettings(Strict):
    """Clinic-configurable business-rule parameters (defaults from FRD §6)."""

    booking_horizon_days: int = Field(default=14, ge=1, le=60)  # BR-2
    change_cutoff_minutes: int = Field(default=60, ge=0, le=1440)  # BR-3
    staff_can_override_cutoff: bool = False  # open question Q13
    max_upcoming_per_doctor: int = Field(default=2, ge=1, le=10)  # BR-4
    token_window_minutes: int = Field(default=60, ge=0, le=240)  # BR-5
    alert_ahead: int = Field(default=3, ge=1, le=20)  # FR-4.3
    quiet_start: time = time(21, 0)  # BR-7
    quiet_end: time = time(8, 0)
    noshow_grace_minutes: int = Field(default=0, ge=0, le=180)  # Q9

    @classmethod
    def from_stored(cls, raw: dict[str, Any] | None) -> ClinicSettings:
        return cls.model_validate(raw or {})


class ClinicCreate(Strict):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(pattern=r"^[A-Z0-9]{3,12}$", description="Clinic code patients type on a shared number")
    specialty: Literal["dental", "physio"]
    languages: list[Literal["gu", "hi", "en"]] = Field(default_factory=lambda: list(_ALL_LANGUAGES), min_length=1)
    address: str | None = Field(default=None, max_length=500)
    map_url: str | None = Field(default=None, max_length=500, pattern=r"^https://")
    phone: str | None = None
    default_fee_paise: int = Field(default=0, ge=0, le=10_000_000)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else v


class ClinicUpdate(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    address: str | None = Field(default=None, max_length=500)
    map_url: str | None = Field(default=None, max_length=500, pattern=r"^https://")
    phone: str | None = None
    languages: list[Literal["gu", "hi", "en"]] | None = None
    default_fee_paise: int | None = Field(default=None, ge=0, le=10_000_000)
    settings: ClinicSettings | None = None
    wa_phone_number_id: str | None = Field(default=None, pattern=r"^\d{6,32}$")
    exotel_number: str | None = None

    @field_validator("exotel_number")
    @classmethod
    def _exo(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else v


class ClinicOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    specialty: str
    timezone: str
    languages: list[str]
    address: str | None
    map_url: str | None
    phone: str | None
    default_fee_paise: int
    settings: ClinicSettings
    status: str
    trial_ends_at: datetime | None
    wa_phone_number_id: str | None = None
    exotel_number: str | None = None
    plan: str = "pilot"


class StaffInvite(Strict):
    phone: str
    name: str | None = Field(default=None, max_length=120)
    role: Literal["doctor", "receptionist", "owner"]
    doctor_id: uuid.UUID | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)


class MembershipOut(BaseModel):
    id: uuid.UUID
    clinic_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    doctor_id: uuid.UUID | None
    status: str
