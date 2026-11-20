"""Missed-call rules (FR-3.2, FR-3.4, FR-3.5) and pilot-plan limits (FR-9.1, FR-9.3). Pure."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

REPEAT_WINDOW = timedelta(minutes=30)  # FR-3.5: repeat calls within 30 min → one message
NO_REPLY_AFTER = timedelta(minutes=15)  # FR-3.3: no reply in 15 min → call back (SMS link is P1)
ANSWERED = {"completed", "answered"}  # Exotel DialCallStatus values that mean someone picked up


def is_missed(dial_status: str | None) -> bool:
    """Exotel forwards on no-answer/busy; anything not answered counts (unknown status = missed, conservative)."""
    return (dial_status or "").strip().lower() not in ANSWERED


def is_repeat(last_called_at: datetime | None, now: datetime) -> bool:
    return last_called_at is not None and now - last_called_at <= REPEAT_WINDOW


# ------------------------------------------------------------------ plans (FR-9.1, FR-9.3)
Plan = Literal["pilot", "basic", "pro"]
PLANS: dict[str, dict[str, int | None]] = {
    # Limits are starting assumptions (pricing is open question Q2); None = unlimited.
    "pilot": {"messages_per_month": 5000, "doctors": 5},
    "basic": {"messages_per_month": 3000, "doctors": 2},
    "pro": {"messages_per_month": 15000, "doctors": 10},
}
WARN_AT = 0.8


def usage_level(used: int, limit: int | None) -> Literal["ok", "warning", "exceeded"]:
    """FR-9.3: warn at 80 % and 100 %."""
    if limit is None or limit <= 0:
        return "ok"
    if used >= limit:
        return "exceeded"
    return "warning" if used >= WARN_AT * limit else "ok"


def days_left(trial_ends_at: datetime | None, now: datetime) -> int | None:
    if trial_ends_at is None:
        return None
    return max(0, (trial_ends_at - now).days + (1 if (trial_ends_at - now).seconds > 0 else 0))
