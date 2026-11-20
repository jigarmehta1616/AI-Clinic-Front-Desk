"""FR-3.2/3.5 missed-call rules; FR-9.1/9.3 plan usage levels."""

from datetime import UTC, datetime, timedelta

import pytest

from clinicdesk.modules.calls.policy import days_left, is_missed, is_repeat, usage_level
from clinicdesk.modules.calls.service import normalize_indian

NOW = datetime(2026, 11, 23, 5, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("status", "missed"),
    [
        ("no-answer", True),
        ("busy", True),
        ("failed", True),
        ("canceled", True),
        (None, True),
        ("", True),
        ("completed", False),
        ("Completed", False),
        ("answered", False),
    ],
)
def test_only_unanswered_calls_count(status, missed):
    assert is_missed(status) is missed


@pytest.mark.parametrize(("minutes_ago", "repeat"), [(None, False), (5, True), (30, True), (31, False)])
def test_repeat_window_30_minutes(minutes_ago, repeat):
    """FR-3.5."""
    last = None if minutes_ago is None else NOW - timedelta(minutes=minutes_ago)
    assert is_repeat(last, NOW) is repeat


@pytest.mark.parametrize(
    ("raw", "out"),
    [
        ("09876543210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("+91 98765 43210", "+919876543210"),
        ("9876543210", "+919876543210"),
        ("12345", None),
        (None, None),
        ("", None),
    ],
)
def test_exotel_number_formats(raw, out):
    assert normalize_indian(raw) == out


@pytest.mark.parametrize(
    ("used", "limit", "level"),
    [
        (0, 100, "ok"),
        (79, 100, "ok"),
        (80, 100, "warning"),
        (99, 100, "warning"),
        (100, 100, "exceeded"),
        (500, None, "ok"),
    ],
)
def test_usage_warning_levels(used, limit, level):
    """FR-9.3: warn at 80 % and 100 %."""
    assert usage_level(used, limit) == level


def test_days_left():
    """FR-9.1."""
    assert days_left(NOW + timedelta(days=90), NOW) == 90
    assert days_left(NOW + timedelta(days=1, hours=2), NOW) == 2
    assert days_left(NOW - timedelta(days=3), NOW) == 0
    assert days_left(None, NOW) is None
