"""Slot computation (FR-1.2, FR-1.3, FR-2.2). Pure: no I/O, `now` injected."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class SessionTemplate:
    weekday: int  # 0 = Monday
    start_time: time
    end_time: time


@dataclass(frozen=True, slots=True)
class DayOff:
    start_date: date
    end_date: date

    def covers(self, d: date) -> bool:
        return self.start_date <= d <= self.end_date


@dataclass(frozen=True, slots=True)
class Slot:
    start: datetime  # aware, UTC
    end: datetime


def local_today(now: datetime, tz: ZoneInfo) -> date:
    return now.astimezone(tz).date()


def _dates(day_from: date, day_to: date) -> Iterator[date]:
    d = day_from
    while d <= day_to:
        yield d
        d += timedelta(days=1)


def generate_slots(
    *,
    sessions: Iterable[SessionTemplate],
    days_off: Iterable[DayOff],
    slot_minutes: int,
    tz: ZoneInfo,
    day_from: date,
    day_to: date,
) -> list[Slot]:
    """All theoretical slots of a doctor between two clinic-local dates (inclusive).

    A slot must fit entirely inside its session; a trailing partial slot is dropped.
    """
    if slot_minutes <= 0:
        raise ValueError("slot_minutes must be positive")
    sessions = list(sessions)
    days_off = list(days_off)
    step = timedelta(minutes=slot_minutes)
    out: list[Slot] = []
    for d in _dates(day_from, day_to):
        if any(x.covers(d) for x in days_off):
            continue
        for s in sorted((s for s in sessions if s.weekday == d.weekday()), key=lambda s: s.start_time):
            start = datetime.combine(d, s.start_time, tzinfo=tz)
            end = datetime.combine(d, s.end_time, tzinfo=tz)
            t = start
            while t + step <= end:
                out.append(Slot(t.astimezone(UTC), (t + step).astimezone(UTC)))
                t += step
    return out


def free_slots(
    slots: Iterable[Slot],
    *,
    taken_starts: set[datetime],
    now: datetime,
    horizon_last_day: date,
    tz: ZoneInfo,
) -> list[Slot]:
    """Future slots, not taken, within the booking horizon (BR-1, BR-2)."""
    return [
        s
        for s in slots
        if s.start > now and s.start not in taken_starts and s.start.astimezone(tz).date() <= horizon_last_day
    ]


def session_window_for(
    sessions: Iterable[SessionTemplate], *, at: datetime, tz: ZoneInfo
) -> tuple[datetime, datetime] | None:
    """The session (as aware UTC bounds) on `at`'s local date that contains `at`, if any."""
    local = at.astimezone(tz)
    for s in sessions:
        if s.weekday != local.weekday():
            continue
        start = datetime.combine(local.date(), s.start_time, tzinfo=tz)
        end = datetime.combine(local.date(), s.end_time, tzinfo=tz)
        if start <= local < end:
            return start.astimezone(UTC), end.astimezone(UTC)
    return None
