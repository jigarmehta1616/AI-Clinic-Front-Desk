"""BR-2, BR-3, BR-4 and appointment status transitions."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from clinicdesk.core.errors import PolicyViolation
from clinicdesk.modules.booking.policy import (
    check_arrival_day,
    check_bookable,
    check_changeable,
    check_transition,
    check_upcoming_limit,
)
from clinicdesk.modules.tenancy.schemas import ClinicSettings

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 23, 5, 0, tzinfo=UTC)  # 10:30 IST Monday
RULES = ClinicSettings()


def code(exc: pytest.ExceptionInfo[PolicyViolation]) -> str:
    return exc.value.code


def test_cannot_book_past_or_now():
    with pytest.raises(PolicyViolation) as e:
        check_bookable(NOW, now=NOW, tz=IST, rules=RULES)
    assert code(e) == "slot_in_past"


def test_horizon_is_inclusive_on_clinic_local_date():
    """BR-2: 14 days ahead allowed (whole local day), 15 not."""
    last_ok = datetime(2026, 12, 7, 18, 0, tzinfo=UTC)  # 7 Dec 23:30 IST = today + 14
    check_bookable(last_ok, now=NOW, tz=IST, rules=RULES)
    too_far = datetime(2026, 12, 7, 18, 31, tzinfo=UTC)  # 8 Dec 00:01 IST
    with pytest.raises(PolicyViolation) as e:
        check_bookable(too_far, now=NOW, tz=IST, rules=RULES)
    assert code(e) == "beyond_horizon"


def test_horizon_configurable():
    rules = ClinicSettings(booking_horizon_days=1)
    with pytest.raises(PolicyViolation):
        check_bookable(NOW + timedelta(days=2), now=NOW, tz=IST, rules=rules)


def test_settings_bounds_enforced():
    """BR-2 clinic can change 1–60 days only."""
    with pytest.raises(ValueError):
        ClinicSettings(booking_horizon_days=61)
    with pytest.raises(ValueError):
        ClinicSettings(booking_horizon_days=0)


@pytest.mark.parametrize(("minutes_before", "ok"), [(61, True), (60, True), (59, False), (0, False), (-10, False)])
def test_change_cutoff(minutes_before: int, ok: bool):
    """BR-3: allowed until exactly 1 hour before."""
    slot = NOW + timedelta(minutes=minutes_before)
    if ok:
        check_changeable(slot, now=NOW, rules=RULES)
    else:
        with pytest.raises(PolicyViolation) as e:
            check_changeable(slot, now=NOW, rules=RULES)
        assert code(e) == "change_cutoff_passed"


def test_staff_override_only_when_clinic_enables_it():
    slot = NOW + timedelta(minutes=10)
    with pytest.raises(PolicyViolation):
        check_changeable(slot, now=NOW, rules=RULES, staff_override=True)
    check_changeable(slot, now=NOW, rules=ClinicSettings(staff_can_override_cutoff=True), staff_override=True)


def test_upcoming_limit():
    """BR-4: 2 allowed; the third is refused."""
    check_upcoming_limit(1, rules=RULES)
    with pytest.raises(PolicyViolation) as e:
        check_upcoming_limit(2, rules=RULES)
    assert code(e) == "max_upcoming_reached"


@pytest.mark.parametrize(
    ("src", "dst", "ok"),
    [
        ("booked", "arrived", True),
        ("confirmed", "no_show", True),
        ("arrived", "completed", True),
        ("arrived", "cancelled", False),
        ("cancelled", "booked", False),
        ("no_show", "arrived", False),
        ("completed", "arrived", False),
    ],
)
def test_transitions(src: str, dst: str, ok: bool):
    if ok:
        check_transition(src, dst)
    else:
        with pytest.raises(PolicyViolation):
            check_transition(src, dst)


def test_arrival_only_on_appointment_day():
    check_arrival_day(NOW + timedelta(hours=2), now=NOW, tz=IST)
    with pytest.raises(PolicyViolation):
        check_arrival_day(NOW + timedelta(days=1), now=NOW, tz=IST)
