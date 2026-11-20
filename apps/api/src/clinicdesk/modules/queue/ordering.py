"""Merged queue ordering (BR-6, FR-4.6, ADR-0005). Pure.

Rule at instant `t`, over waiting entries that are present:
  0. recalled (priority) entries               → earliest issue
  1. booked + arrived with slot_start <= t   → earliest slot_start
  2. walk-in                                  → lowest token number (issue order)
  3. booked + arrived early (slot_start > t)  → earliest slot_start
Projection treats not-yet-arrived bookings as arriving exactly at slot_start.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

Kind = Literal["booked", "walk_in"]
Status = Literal["waiting", "called", "skipped", "completed", "cancelled"]


@dataclass(frozen=True, slots=True)
class QueueItem:
    id: uuid.UUID
    kind: Kind
    status: Status
    issued_at: datetime
    token_no: int | None = None
    slot_start: datetime | None = None  # booked only
    arrived: bool = True  # walk-ins are present once issued
    priority: bool = False  # a skipped token recalled by staff goes next (FR-4.4)


@dataclass(frozen=True, slots=True)
class Projected:
    item: QueueItem
    eta: datetime
    ahead: int


def _pick(candidates: Sequence[QueueItem], t: datetime) -> QueueItem | None:
    recalled = [c for c in candidates if c.priority]
    if recalled:
        return min(recalled, key=lambda c: c.issued_at)
    due = [c for c in candidates if c.kind == "booked" and c.slot_start is not None and c.slot_start <= t]
    if due:
        return min(due, key=lambda c: (c.slot_start, c.issued_at))
    walk = [c for c in candidates if c.kind == "walk_in"]
    if walk:
        return min(walk, key=lambda c: (c.token_no if c.token_no is not None else 1 << 30, c.issued_at))
    early = [c for c in candidates if c.kind == "booked"]
    if early:
        return min(early, key=lambda c: (c.slot_start or t, c.issued_at))
    return None


def next_item(items: Iterable[QueueItem], now: datetime) -> QueueItem | None:
    """Entry to call when staff tap "Next" (FR-4.4). Only present, waiting entries qualify."""
    present = [i for i in items if i.status == "waiting" and (i.kind == "walk_in" or i.arrived)]
    return _pick(present, now)


def project_order(
    items: Iterable[QueueItem],
    *,
    now: datetime,
    avg_consult: timedelta,
    in_consult_remaining: timedelta | None = None,
) -> list[Projected]:
    """Simulated calling order with ETAs (FR-4.2 wait estimate, FR-4.3 'N ahead').

    `in_consult_remaining`: time left for the patient currently with the doctor, if any.
    """
    if avg_consult <= timedelta(0):
        raise ValueError("avg_consult must be positive")
    pool = [i for i in items if i.status == "waiting"]
    t = now + (in_consult_remaining or timedelta(0))
    out: list[Projected] = []
    while pool:
        available = [
            i for i in pool if i.kind == "walk_in" or i.arrived or (i.slot_start is not None and i.slot_start <= t)
        ]
        if not available:
            # Only future, not-yet-arrived bookings remain: doctor idles until the next slot.
            t = min(i.slot_start for i in pool if i.slot_start is not None)
            continue
        chosen = _pick(available, t)
        assert chosen is not None
        out.append(Projected(item=chosen, eta=t, ahead=len(out)))
        pool.remove(chosen)
        t += avg_consult
    return out
