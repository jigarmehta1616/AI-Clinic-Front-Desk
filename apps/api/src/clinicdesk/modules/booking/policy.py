"""Booking business rules BR-2, BR-3, BR-4 and status transitions. Pure."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from clinicdesk.core.errors import PolicyViolation
from clinicdesk.modules.tenancy.schemas import ClinicSettings

# Allowed status transitions (from → to). Anything else is a PolicyViolation.
TRANSITIONS: dict[str, frozenset[str]] = {
    "booked": frozenset({"confirmed", "arrived", "cancelled", "rescheduled", "no_show"}),
    "confirmed": frozenset({"arrived", "cancelled", "rescheduled", "no_show"}),
    "arrived": frozenset({"completed"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
    "rescheduled": frozenset(),
    "no_show": frozenset(),
}


def check_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, frozenset()):
        raise PolicyViolation(
            f"cannot change appointment from {current} to {target}",
            code="invalid_transition",
            details={"from": current, "to": target},
        )


def check_bookable(slot_start: datetime, *, now: datetime, tz: ZoneInfo, rules: ClinicSettings) -> None:
    """BR-2: future slot, at most `booking_horizon_days` clinic-local days ahead."""
    if slot_start <= now:
        raise PolicyViolation("slot is in the past", code="slot_in_past")
    last_day = now.astimezone(tz).date() + timedelta(days=rules.booking_horizon_days)
    if slot_start.astimezone(tz).date() > last_day:
        raise PolicyViolation(
            f"bookings allowed up to {rules.booking_horizon_days} days ahead",
            code="beyond_horizon",
            details={"horizon_days": rules.booking_horizon_days},
        )


def check_changeable(
    slot_start: datetime, *, now: datetime, rules: ClinicSettings, staff_override: bool = False
) -> None:
    """BR-3: reschedule/cancel allowed until `change_cutoff_minutes` before the slot."""
    if staff_override and rules.staff_can_override_cutoff:
        return
    if now > slot_start - timedelta(minutes=rules.change_cutoff_minutes):
        raise PolicyViolation(
            f"changes allowed until {rules.change_cutoff_minutes} minutes before the appointment",
            code="change_cutoff_passed",
            details={"cutoff_minutes": rules.change_cutoff_minutes},
        )


def check_upcoming_limit(current_upcoming: int, *, rules: ClinicSettings) -> None:
    """BR-4: at most N upcoming bookings per phone per doctor."""
    if current_upcoming >= rules.max_upcoming_per_doctor:
        raise PolicyViolation(
            f"at most {rules.max_upcoming_per_doctor} upcoming bookings per doctor for one number",
            code="max_upcoming_reached",
            details={"limit": rules.max_upcoming_per_doctor},
        )


def check_arrival_day(slot_start: datetime, *, now: datetime, tz: ZoneInfo) -> None:
    """Arrival can only be marked on the appointment's clinic-local day."""
    if slot_start.astimezone(tz).date() != now.astimezone(tz).date():
        raise PolicyViolation("arrival can only be marked on the appointment day", code="not_appointment_day")
