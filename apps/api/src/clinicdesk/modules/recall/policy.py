"""Reminders (FR-5.1), recall lifecycle (FR-6.3/6.4, BR-8) and revenue attribution (BR-11/BR-12). Pure.

Recall lifecycle: scheduled → sent (initial) → follow-up 1 → follow-up 2 → lapsed, unless booked / declined /
cancelled (already booked) / skipped (opted out or no consent) first. Follow-ups are relative to the first send
(FRD: "default 3 and 7 days later"); the recall lapses `LAPSE_AFTER` days after the last follow-up.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

REMINDER_OFFSETS: dict[str, timedelta] = {"24h": timedelta(hours=24), "2h": timedelta(hours=2)}
RECALL_SEND_TIME = time(10, 0)  # clinic-local; AC-7 requires "on due date at or after 8 am"
RECALL_CAP = timedelta(days=3)  # BR-8: ≤ 1 recall message per clinic per 3 days
LAPSE_AFTER = timedelta(days=3)
ATTRIBUTION_WINDOW = timedelta(days=7)  # open question Q6
RECOVERY_SOURCES = ("missed_call", "recall", "noshow_rebook")


def reminder_times(slot_start: datetime, *, now: datetime) -> dict[str, datetime]:
    """Reminder instants still in the future (a booking made 3 h ahead gets only the 2 h reminder)."""
    return {k: slot_start - off for k, off in REMINDER_OFFSETS.items() if slot_start - off > now}


def recall_due_date(visit_day: date, delay_days: int) -> date:
    return visit_day + timedelta(days=delay_days)


def recall_send_at(due: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(due, RECALL_SEND_TIME, tzinfo=tz)


NextStep = tuple[Literal["followup", "lapse"], datetime]


def next_step(*, sends: int, first_sent_at: datetime, last_sent_at: datetime, followup_days: list[int]) -> NextStep:
    """What to do after the `sends`-th message (1 = initial) went out."""
    if sends <= len(followup_days):
        return "followup", first_sent_at + timedelta(days=followup_days[sends - 1])
    return "lapse", last_sent_at + LAPSE_AFTER


def max_sends(followup_days: list[int]) -> int:
    return 1 + min(len(followup_days), 2)  # FR-6.4: at most 2 follow-ups


def cap_deferral(last_recall_message_at: datetime | None, now: datetime) -> datetime | None:
    """BR-8: if this clinic sent the patient a recall < 3 days ago, the earliest permitted time; else None."""
    if last_recall_message_at is not None and now < last_recall_message_at + RECALL_CAP:
        return last_recall_message_at + RECALL_CAP
    return None


def attributable(source: str, *, trigger_at: datetime | None, booked_at: datetime) -> bool:
    """BR-11 pre-condition (arrival is checked by the caller): booked from a recovery message, within the window."""
    if source not in RECOVERY_SOURCES or trigger_at is None:
        return False
    return timedelta(0) <= booked_at - trigger_at <= ATTRIBUTION_WINDOW


def fee_snapshot(doctor_fee_paise: int | None, clinic_default_paise: int) -> int:
    """BR-12: the doctor's consultation fee set by the clinic (clinic default when unset — Q5)."""
    return doctor_fee_paise if doctor_fee_paise is not None else clinic_default_paise


SPECIALTY_RULES: dict[str, list[dict[str, object]]] = {
    # FR-1.6 starting points; every clinic can edit them (FR-6.1).
    "dental": [
        {"visit_type": "checkup", "label": "Dental check-up", "delay_days": 182, "plan_based": False},
        {"visit_type": "cleaning", "label": "Scaling & cleaning", "delay_days": 182, "plan_based": False},
        {"visit_type": "rct_review", "label": "Root canal review", "delay_days": 7, "plan_based": False},
        {"visit_type": "extraction_review", "label": "Extraction review", "delay_days": 7, "plan_based": False},
    ],
    "physio": [
        {"visit_type": "physio_session", "label": "Physiotherapy session", "delay_days": 2, "plan_based": True},
        {"visit_type": "physio_review", "label": "Physiotherapy review", "delay_days": 14, "plan_based": False},
        {"visit_type": "assessment", "label": "Assessment follow-up", "delay_days": 7, "plan_based": False},
    ],
}
