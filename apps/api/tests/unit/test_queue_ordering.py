"""BR-6, FR-4.4, FR-4.6 — merged queue ordering (ADR-0005)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from clinicdesk.modules.queue.ordering import QueueItem, next_item, project_order

T0 = datetime(2026, 11, 23, 4, 30, tzinfo=UTC)  # 10:00 IST
M = timedelta(minutes=1)


def walk(token: int, issued_min: int = 0, status: str = "waiting") -> QueueItem:
    return QueueItem(uuid.uuid4(), "walk_in", status, T0 + issued_min * M, token_no=token)  # type: ignore[arg-type]


def booked(slot_min: int, arrived: bool = True, status: str = "waiting") -> QueueItem:
    return QueueItem(
        uuid.uuid4(),
        "booked",
        status,
        T0,
        slot_start=T0 + slot_min * M,
        arrived=arrived,  # type: ignore[arg-type]
    )


def test_due_booked_patient_goes_before_walkins():
    b = booked(0)
    w = walk(1)
    assert next_item([w, b], T0) == b


def test_walkins_fill_gap_before_booked_slot():
    """Booked at 10:30 arrived early; at 10:05 the walk-in goes first."""
    b = booked(30)
    w = walk(1)
    assert next_item([b, w], T0 + 5 * M) == w


def test_early_booked_called_when_no_walkins():
    b = booked(30)
    assert next_item([b], T0) == b


def test_walkins_in_token_order_regardless_of_list_order():
    w1, w2, w3 = walk(1, 0), walk(2, 1), walk(3, 2)
    assert next_item([w3, w1, w2], T0) == w1


def test_arrived_booked_keep_slot_order():
    late_slot, early_slot = booked(20), booked(10)
    assert next_item([late_slot, early_slot], T0 + 25 * M) == early_slot


def test_not_arrived_booked_and_skipped_are_not_called():
    """FR-4.4: skipped tokens leave the order until recalled."""
    assert next_item([booked(0, arrived=False), walk(1, status="skipped")], T0) is None


def test_projection_merges_and_estimates():
    """FR-4.2 / FR-4.3: walk-ins fill gaps; booked patient slotted at their time."""
    w1, w2, w3 = walk(1), walk(2), walk(3)
    b = booked(20, arrived=False)  # expected at 10:20
    order = project_order([w1, w2, w3, b], now=T0, avg_consult=10 * M)
    assert [p.item for p in order] == [w1, w2, b, w3]
    assert [p.eta for p in order] == [T0, T0 + 10 * M, T0 + 20 * M, T0 + 30 * M]
    assert [p.ahead for p in order] == [0, 1, 2, 3]


def test_projection_idles_until_future_booking():
    b = booked(45, arrived=False)
    order = project_order([b], now=T0, avg_consult=10 * M)
    assert order[0].eta == T0 + 45 * M


def test_projection_accounts_for_patient_in_consult():
    order = project_order([walk(1)], now=T0, avg_consult=10 * M, in_consult_remaining=4 * M)
    assert order[0].eta == T0 + 4 * M


def test_projection_rejects_non_positive_consult():
    with pytest.raises(ValueError):
        project_order([], now=T0, avg_consult=timedelta(0))
