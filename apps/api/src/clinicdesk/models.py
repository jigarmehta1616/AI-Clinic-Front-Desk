"""Model registry: importing this module registers every table on Base.metadata (Alembic, tests)."""

from clinicdesk.core.db import Base
from clinicdesk.modules.audit.models import AuditLog
from clinicdesk.modules.auth.models import OtpChallenge, RefreshToken
from clinicdesk.modules.booking.models import Appointment
from clinicdesk.modules.calls.models import MissedCall
from clinicdesk.modules.jobs.models import ScheduledJob
from clinicdesk.modules.messaging.models import Conversation, HandoverTicket, InboundEvent, Message, OutboxMessage
from clinicdesk.modules.patients.models import ConsentEvent, Patient
from clinicdesk.modules.queue.models import QueueEntry, QueueSession
from clinicdesk.modules.recall.models import Recall, RecallRule, RecoveryAttribution, TreatmentPlan
from clinicdesk.modules.scheduling.models import Doctor, DoctorSession, ScheduleException
from clinicdesk.modules.tenancy.models import Clinic, ClinicMembership, User

PLATFORM_TABLES = frozenset({"users", "otp_challenges", "refresh_tokens", "inbound_events"})

__all__ = [
    "PLATFORM_TABLES",
    "Appointment",
    "AuditLog",
    "Base",
    "Clinic",
    "ClinicMembership",
    "ConsentEvent",
    "Conversation",
    "Doctor",
    "DoctorSession",
    "HandoverTicket",
    "InboundEvent",
    "Message",
    "MissedCall",
    "OtpChallenge",
    "OutboxMessage",
    "Patient",
    "QueueEntry",
    "QueueSession",
    "Recall",
    "RecallRule",
    "RecoveryAttribution",
    "RefreshToken",
    "ScheduleException",
    "ScheduledJob",
    "TreatmentPlan",
    "User",
]
