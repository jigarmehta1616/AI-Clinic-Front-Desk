"""FR-5.1 reminder timing, FR-6.4 follow-ups/lapse, BR-8 cap, BR-11/12 attribution rules, FR-1.6 templates."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from clinicdesk.modules.recall.policy import (
    SPECIALTY_RULES,
    attributable,
    cap_deferral,
    fee_snapshot,
    max_sends,
    next_step,
    recall_due_date,
    recall_send_at,
    reminder_times,
)

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 23, 3, 30, tzinfo=UTC)  # Mon 09:00 IST
D = timedelta(days=1)


def test_reminders_24h_and_2h_only_if_future():
    slot = NOW + 2 * D
    assert reminder_times(slot, now=NOW) == {"24h": slot - D, "2h": slot - timedelta(hours=2)}
    soon = NOW + timedelta(hours=5)
    assert reminder_times(soon, now=NOW) == {"2h": soon - timedelta(hours=2)}
    assert reminder_times(NOW + timedelta(hours=1), now=NOW) == {}


def test_recall_due_and_send_time_after_8am():
    """AC-7: due date at or after 08:00 clinic time."""
    assert recall_due_date(date(2026, 11, 23), 182) == date(2027, 5, 24)
    at = recall_send_at(date(2027, 5, 24), IST)
    assert at.astimezone(IST).hour >= 8 and at.astimezone(IST).date() == date(2027, 5, 24)


def test_followups_relative_to_first_send_then_lapse():
    """FR-6.4: initial, +3 d, +7 d, then lapse."""
    first = NOW
    assert next_step(sends=1, first_sent_at=first, last_sent_at=first, followup_days=[3, 7]) == (
        "followup",
        first + 3 * D,
    )
    assert next_step(sends=2, first_sent_at=first, last_sent_at=first + 3 * D, followup_days=[3, 7]) == (
        "followup",
        first + 7 * D,
    )
    kind, at = next_step(sends=3, first_sent_at=first, last_sent_at=first + 7 * D, followup_days=[3, 7])
    assert kind == "lapse" and at == first + 10 * D
    assert max_sends([3, 7]) == 3 and max_sends([]) == 1 and max_sends([1, 2, 3]) == 3


@pytest.mark.parametrize(("ago_hours", "deferred"), [(None, False), (71, True), (72, False), (100, False)])
def test_three_day_recall_cap(ago_hours, deferred):
    """BR-8."""
    last = None if ago_hours is None else NOW - timedelta(hours=ago_hours)
    result = cap_deferral(last, NOW)
    assert (result is not None) is deferred
    if deferred:
        assert result == last + 3 * D


@pytest.mark.parametrize(
    ("source", "trigger_offset", "booked_offset", "ok"),
    [
        ("recall", 0, 1, True),
        ("recall", 0, 7 * 24, True),
        ("recall", 0, 7 * 24 + 1, False),
        ("recall", 5, 1, False),  # booked before the message
        ("noshow_rebook", 0, 2, True),
        ("staff", 0, 1, False),
        ("assistant", 0, 1, False),
    ],
)
def test_attribution_window(source, trigger_offset, booked_offset, ok):
    """BR-11 pre-condition + Q6 window."""
    trigger = NOW + timedelta(hours=trigger_offset)
    assert attributable(source, trigger_at=trigger, booked_at=NOW + timedelta(hours=booked_offset)) is ok
    assert attributable("recall", trigger_at=None, booked_at=NOW) is False


def test_fee_snapshot_uses_doctor_fee_else_clinic_default():
    """BR-12 / Q5."""
    assert fee_snapshot(70000, 50000) == 70000
    assert fee_snapshot(None, 50000) == 50000
    assert fee_snapshot(0, 50000) == 0


def test_specialty_templates():
    """FR-1.6: dental 6-month recalls; physio plan-based sessions."""
    dental = {r["visit_type"]: r for r in SPECIALTY_RULES["dental"]}
    assert dental["cleaning"]["delay_days"] == 182 and dental["checkup"]["delay_days"] == 182
    physio = {r["visit_type"]: r for r in SPECIALTY_RULES["physio"]}
    assert physio["physio_session"]["plan_based"] is True and physio["physio_session"]["delay_days"] == 2
