"""Who is acting, for which tenant, through which channel. Built only from verified credentials."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Literal

ActorType = Literal["user", "patient", "system", "assistant", "anonymous"]
Channel = Literal["dashboard", "whatsapp", "system", "api"]


@dataclass(frozen=True, slots=True)
class RequestContext:
    actor_type: ActorType
    actor_id: uuid.UUID | None
    clinic_id: uuid.UUID | None
    role: str | None
    channel: Channel
    request_id: str | None = None
    doctor_id: uuid.UUID | None = None  # set when role == doctor
    is_platform_admin: bool = False

    @property
    def tenant(self) -> uuid.UUID:
        if self.clinic_id is None:
            from clinicdesk.core.errors import Forbidden

            raise Forbidden("no clinic selected", code="no_clinic_selected")
        return self.clinic_id

    def for_clinic(self, clinic_id: uuid.UUID, role: str | None) -> RequestContext:
        return replace(self, clinic_id=clinic_id, role=role)


def system_context(clinic_id: uuid.UUID | None, request_id: str | None = None) -> RequestContext:
    return RequestContext("system", None, clinic_id, None, "system", request_id)
