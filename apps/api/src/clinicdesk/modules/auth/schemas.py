from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator

from clinicdesk.modules.tenancy.schemas import Strict, normalize_phone


class OtpRequest(Strict):
    phone: str

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)


class OtpVerify(OtpRequest):
    code: str = Field(pattern=r"^\d{6}$")


class SelectClinic(Strict):
    clinic_id: uuid.UUID


class MembershipSummary(BaseModel):
    clinic_id: uuid.UUID
    clinic_name: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    clinic_id: uuid.UUID | None
    role: str | None
    memberships: list[MembershipSummary] = []


class Me(BaseModel):
    user_id: uuid.UUID
    phone: str
    name: str | None
    clinic_id: uuid.UUID | None
    role: str | None
    memberships: list[MembershipSummary]
