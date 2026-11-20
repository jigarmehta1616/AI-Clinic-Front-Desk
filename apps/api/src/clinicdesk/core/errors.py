"""Domain errors with stable codes; mapped to HTTP in main.py."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}


class PolicyViolation(DomainError):
    status_code = 422
    code = "policy_violation"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class SlotTaken(Conflict):
    code = "slot_taken"


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"


class Unauthorized(DomainError):
    status_code = 401
    code = "unauthorized"


class RateLimited(DomainError):
    status_code = 429
    code = "rate_limited"
