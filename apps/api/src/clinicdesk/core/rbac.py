"""Role → permission matrix (FRD §3)."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    DOCTOR = "doctor"
    RECEPTIONIST = "receptionist"


class Permission(StrEnum):
    CLINIC_READ = "clinic.read"
    CLINIC_MANAGE = "clinic.manage"
    STAFF_MANAGE = "staff.manage"
    DOCTOR_MANAGE = "doctor.manage"
    SCHEDULE_READ = "schedule.read"
    PATIENT_READ = "patient.read"
    PATIENT_WRITE = "patient.write"
    APPOINTMENT_READ = "appointment.read"
    APPOINTMENT_BOOK = "appointment.book"  # book / reschedule / cancel
    APPOINTMENT_STATUS = "appointment.status"  # arrived / no-show / completed
    AUDIT_READ = "audit.read"
    BILLING_MANAGE = "billing.manage"
    RECALL_RULES_MANAGE = "recall_rules.manage"
    QUEUE_ISSUE = "queue.issue"  # issue walk-in tokens
    QUEUE_OPERATE = "queue.operate"  # call next, skip, recall, complete
    INBOX_HANDLE = "inbox.handle"  # read/reply to escalated chats (FR-8.x)
    REPORTS_READ = "reports.read"  # revenue reports (owner)
    CALLS_HANDLE = "calls.handle"  # missed-call list (FR-3.4)


_RECEPTIONIST = {
    Permission.CLINIC_READ,
    Permission.SCHEDULE_READ,
    Permission.PATIENT_READ,
    Permission.PATIENT_WRITE,
    Permission.APPOINTMENT_READ,
    Permission.APPOINTMENT_BOOK,
    Permission.APPOINTMENT_STATUS,
    Permission.QUEUE_ISSUE,
    Permission.QUEUE_OPERATE,
    Permission.INBOX_HANDLE,
    Permission.CALLS_HANDLE,
}
_DOCTOR = {
    Permission.CLINIC_READ,
    Permission.SCHEDULE_READ,
    Permission.PATIENT_READ,
    Permission.APPOINTMENT_READ,
    Permission.APPOINTMENT_STATUS,
    Permission.QUEUE_OPERATE,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(Permission),
    Role.RECEPTIONIST: frozenset(_RECEPTIONIST),
    Role.DOCTOR: frozenset(_DOCTOR),
}


def has_permission(role: Role | str | None, perm: Permission) -> bool:
    if role is None:
        return False
    try:
        return perm in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False
