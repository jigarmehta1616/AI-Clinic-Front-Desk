"""Quiet hours (BR-7). Pure.

Transactional replies (answers to a patient's own message, booking confirmations, emergency replies)
are exempt. Reminders, recalls and promotional messages scheduled inside the quiet window are deferred
to the window's end (08:00 clinic-local by default).
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

Category = Literal["transactional", "reminder", "recall", "promo"]


def in_quiet_hours(at: datetime, *, tz: ZoneInfo, start: time = time(21), end: time = time(8)) -> bool:
    t = at.astimezone(tz).time()
    if start > end:  # window wraps midnight (default 21:00–08:00)
        return t >= start or t < end
    return start <= t < end


def adjust_send_time(
    scheduled: datetime,
    category: Category,
    *,
    tz: ZoneInfo,
    start: time = time(21),
    end: time = time(8),
    deadline: datetime | None = None,
) -> datetime | None:
    """Earliest permissible send time, or None if deferral would pass `deadline` (e.g. the appointment)."""
    if category == "transactional" or not in_quiet_hours(scheduled, tz=tz, start=start, end=end):
        result = scheduled
    else:
        local = scheduled.astimezone(tz)
        day = local.date() if local.time() < end else local.date() + timedelta(days=1)
        result = datetime.combine(day, end, tzinfo=tz).astimezone(UTC)
    if deadline is not None and result >= deadline:
        return None
    return result
