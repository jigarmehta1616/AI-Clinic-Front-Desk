"""BR-5 token window/limit, FR-4.4 recall priority, FR-4.7 average, job backoff (NFR-5)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from clinicdesk.core.errors import PolicyViolation
from clinicdesk.modules.jobs.policy import BACKOFF, next_attempt, should_give_up
from clinicdesk.modules.queue.ordering import QueueItem, next_item, project_order
from clinicdesk.modules.queue.policy import average_consult, check_token_limit, check_token_window

T0 = datetime(2026, 11, 23, 4, 30, tzinfo=UTC)  # session start 10:00 IST
END = T0 + timedelta(hours=3)
M = timedelta(minutes=1)


@pytest.mark.parametrize(
    ("offset_min", "code"),
    [(-61, "token_window_not_open"), (-60, None), (0, None), (179, None), (180, "session_ended")],
)
def test_token_window(offset_min, code):
    """BR-5: from 1 h before start until session end."""
    now = T0 + offset_min * M
    if code is None:
        check_token_window(now=now, starts_at=T0, ends_at=END, window_minutes=60)
    else:
        with pytest.raises(PolicyViolation) as e:
            check_token_window(now=now, starts_at=T0, ends_at=END, window_minutes=60)
        assert e.value.code == code


def test_token_limit():
    """BR-5: stop at the session's token limit."""
    check_token_limit(29, max_tokens=30)
    with pytest.raises(PolicyViolation) as e:
        check_token_limit(30, max_tokens=30)
    assert e.value.code == "token_limit_reached"


def test_recalled_token_goes_next_even_before_due_booking():
    """FR-4.4: a recalled skipped token is called next."""
    booked = QueueItem(uuid.uuid4(), "booked", "waiting", T0, slot_start=T0)
    walk = QueueItem(uuid.uuid4(), "walk_in", "waiting", T0, token_no=1)
    recalled = QueueItem(uuid.uuid4(), "walk_in", "waiting", T0 + M, token_no=5, priority=True)
    assert next_item([booked, walk, recalled], T0 + 5 * M) == recalled
    assert project_order([booked, walk, recalled], now=T0, avg_consult=10 * M)[0].item == recalled


def test_average_consult_needs_enough_samples_and_ignores_outliers():
    """FR-4.7."""
    fallback = timedelta(minutes=15)
    assert average_consult([timedelta(minutes=8)] * 9, fallback=fallback) == fallback
    samples = [timedelta(minutes=8)] * 10 + [timedelta(seconds=5), timedelta(hours=5)]
    assert average_consult(samples, fallback=fallback) == timedelta(minutes=8)


def test_job_backoff_and_give_up():
    assert next_attempt(T0, 1) == T0 + BACKOFF[0]
    assert next_attempt(T0, 99) == T0 + BACKOFF[-1]
    assert not should_give_up(5, 6)
    assert should_give_up(6, 6)
