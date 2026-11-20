"""BR-7 — quiet hours 21:00–08:00 IST."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from clinicdesk.modules.messaging.quiet_hours import adjust_send_time, in_quiet_hours

IST = ZoneInfo("Asia/Kolkata")
D = date(2026, 11, 23)


def ist(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(h, m), tzinfo=IST).astimezone(UTC)


@pytest.mark.parametrize(
    ("h", "m", "quiet"),
    [
        (20, 59, False),
        (21, 0, True),
        (23, 30, True),
        (0, 0, True),
        (7, 59, True),
        (8, 0, False),
        (12, 0, False),
    ],
)
def test_window_edges(h: int, m: int, quiet: bool):
    assert in_quiet_hours(ist(D, h, m), tz=IST) is quiet


def test_recall_at_night_defers_to_next_morning():
    assert adjust_send_time(ist(D, 22), "recall", tz=IST) == ist(date(2026, 11, 24), 8)


def test_reminder_early_morning_defers_same_day():
    assert adjust_send_time(ist(D, 6, 30), "reminder", tz=IST) == ist(D, 8)


def test_transactional_never_deferred():
    assert adjust_send_time(ist(D, 23), "transactional", tz=IST) == ist(D, 23)


def test_outside_window_unchanged():
    assert adjust_send_time(ist(D, 9), "promo", tz=IST) == ist(D, 9)


def test_deferral_past_deadline_is_dropped():
    """2-hour reminder for a 07:30 appointment would land after the appointment → skip."""
    assert adjust_send_time(ist(D, 5, 30), "reminder", tz=IST, deadline=ist(D, 7, 30)) is None
