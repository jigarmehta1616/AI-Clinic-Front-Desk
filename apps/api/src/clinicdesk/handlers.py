"""Importing this module registers every background job handler (API and worker both import it)."""

from clinicdesk.modules.assistant import pipeline  # noqa: F401  wa.inbound
from clinicdesk.modules.calls import service as calls_service  # noqa: F401  exotel.inbound, missedcall.followup
from clinicdesk.modules.messaging import service  # noqa: F401  wa.send
from clinicdesk.modules.recall import reminders  # noqa: F401  reminder.send, recall.send
