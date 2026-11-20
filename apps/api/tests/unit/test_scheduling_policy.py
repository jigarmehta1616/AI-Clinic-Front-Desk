"""FR-1.2, FR-1.3, FR-2.2, BR-2 — slot generation."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from clinicdesk.modules.scheduling.policy import (
    DayOff,
    SessionTemplate,
    free_slots,
    generate_slots,
    session_window_for,
)

IST = ZoneInfo("Asia/Kolkata")
MON = date(2026, 11, 23)
assert MON.weekday() == 0


def ist(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(h, m), tzinfo=IST).astimezone(UTC)


MORNING = SessionTemplate(0, time(10), time(13))
EVENING = SessionTemplate(0, time(17), time(19, 50))


def test_slots_fill_session_and_drop_partial_trailing_slot():
    """FR-1.2: 17:00–19:50 with 20-min slots → 8 slots, last 19:20–19:40."""
    slots = generate_slots(sessions=[EVENING], days_off=[], slot_minutes=20, tz=IST, day_from=MON, day_to=MON)
    assert len(slots) == 8
    assert slots[0].start == ist(MON, 17)
    assert slots[-1].end == ist(MON, 19, 40)


def test_multiple_sessions_sorted_and_only_matching_weekday():
    slots = generate_slots(
        sessions=[EVENING, MORNING],
        days_off=[],
        slot_minutes=30,
        tz=IST,
        day_from=MON,
        day_to=MON + timedelta(days=1),
    )
    assert [s.start for s in slots[:2]] == [ist(MON, 10), ist(MON, 10, 30)]
    assert all(s.start.astimezone(IST).date() == MON for s in slots)  # Tuesday has no session
    assert len(slots) == 6 + 5


def test_holiday_and_leave_remove_whole_day():
    """FR-1.3."""
    slots = generate_slots(
        sessions=[MORNING], days_off=[DayOff(MON, MON)], slot_minutes=15, tz=IST, day_from=MON, day_to=MON
    )
    assert slots == []


def test_free_slots_excludes_past_taken_and_beyond_horizon():
    """BR-1 (taken), BR-2 (horizon)."""
    slots = generate_slots(
        sessions=[MORNING], days_off=[], slot_minutes=60, tz=IST, day_from=MON, day_to=MON + timedelta(days=7)
    )
    now = ist(MON, 10, 30)
    free = free_slots(slots, taken_starts={ist(MON, 12)}, now=now, horizon_last_day=MON, tz=IST)
    assert [s.start for s in free] == [ist(MON, 11)]


def test_session_window_lookup():
    window = session_window_for([MORNING], at=ist(MON, 11), tz=IST)
    assert window == (ist(MON, 10), ist(MON, 13))
    assert session_window_for([MORNING], at=ist(MON, 13), tz=IST) is None
