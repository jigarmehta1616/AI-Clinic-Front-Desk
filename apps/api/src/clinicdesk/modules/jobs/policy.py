"""Retry/backoff for scheduled jobs. Pure."""

from __future__ import annotations

from datetime import datetime, timedelta

BACKOFF = (
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=6),
)
STALE_LOCK = timedelta(minutes=10)


def next_attempt(now: datetime, attempts: int) -> datetime:
    """`attempts` = attempts already made (≥ 1)."""
    return now + BACKOFF[min(max(attempts, 1), len(BACKOFF)) - 1]


def should_give_up(attempts: int, max_attempts: int) -> bool:
    return attempts >= max_attempts
