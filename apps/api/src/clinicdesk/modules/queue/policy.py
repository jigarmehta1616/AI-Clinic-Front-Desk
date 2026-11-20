"""Walk-in token rules (BR-5) and wait-time inputs (FR-4.7). Pure."""

from __future__ import annotations

from datetime import datetime, timedelta

from clinicdesk.core.errors import PolicyViolation

MIN_SAMPLES_FOR_AVERAGE = 10


def check_token_window(*, now: datetime, starts_at: datetime, ends_at: datetime, window_minutes: int) -> None:
    """BR-5: tokens only during the session or up to `window_minutes` before it starts."""
    if now >= ends_at:
        raise PolicyViolation("this session has ended", code="session_ended")
    if now < starts_at - timedelta(minutes=window_minutes):
        raise PolicyViolation(
            f"tokens open {window_minutes} minutes before the session",
            code="token_window_not_open",
            details={"opens_at": (starts_at - timedelta(minutes=window_minutes)).isoformat()},
        )


def check_token_limit(walk_ins_issued: int, *, max_tokens: int) -> None:
    """BR-5: stop at the session's token limit (counts walk-in tokens; open question Q14)."""
    if walk_ins_issued >= max_tokens:
        raise PolicyViolation("no more tokens for this session", code="token_limit_reached")


def average_consult(durations: list[timedelta], *, fallback: timedelta) -> timedelta:
    """FR-4.7: doctor's average consult time; slot length until enough history exists."""
    usable = [d for d in durations if timedelta(minutes=1) <= d <= timedelta(hours=2)]
    if len(usable) < MIN_SAMPLES_FOR_AVERAGE:
        return fallback
    return sum(usable, timedelta(0)) / len(usable)
