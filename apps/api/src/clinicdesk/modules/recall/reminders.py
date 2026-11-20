"""Appointment reminders 24 h and 2 h before, with Confirm / Reschedule / Cancel buttons (FR-5.1, AC-4).

Scheduled when an appointment is booked or rescheduled; every check is repeated when the job runs
(still upcoming? quiet hours? would deferral pass the appointment?). Consent and opt-out are enforced by the
dispatcher (category `reminder`).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.modules.booking.models import UPCOMING_STATUSES, Appointment
from clinicdesk.modules.jobs import service as jobs
from clinicdesk.modules.messaging import service as messaging
from clinicdesk.modules.messaging.quiet_hours import adjust_send_time
from clinicdesk.modules.messaging.templates import fmt_date, fmt_time, t, template_ref
from clinicdesk.modules.recall import policy
from clinicdesk.modules.scheduling.models import Doctor
from clinicdesk.modules.tenancy.models import Clinic
from clinicdesk.modules.tenancy.schemas import ClinicSettings

MIN_LEAD = timedelta(minutes=15)  # never remind less than 15 minutes before the slot


async def schedule_for(s: AsyncSession, appt: Appointment, now: datetime) -> None:
    for kind, run_at in policy.reminder_times(appt.slot_start, now=now).items():
        await jobs.enqueue(
            s,
            clinic_id=appt.clinic_id,
            kind="reminder.send",
            run_at=run_at,
            dedup_key=f"reminder:{appt.id}:{kind}",
            payload={"appointment_id": str(appt.id), "kind": kind},
        )


async def send_reminder(jc: jobs.JobContext) -> None:
    s, now = jc.s, jc.rt.clock.now()
    appt = await s.get(Appointment, uuid.UUID(jc.job.payload["appointment_id"]))
    if appt is None or appt.status not in UPCOMING_STATUSES or appt.slot_start <= now + MIN_LEAD:
        return  # cancelled / rescheduled / too late: nothing to send
    clinic = await s.get(Clinic, appt.clinic_id)
    assert clinic is not None
    tz, rules = ZoneInfo(clinic.timezone), ClinicSettings.from_stored(clinic.settings)
    allowed = adjust_send_time(
        now, "reminder", tz=tz, start=rules.quiet_start, end=rules.quiet_end, deadline=appt.slot_start - MIN_LEAD
    )
    if allowed is None:
        return  # BR-7 deferral would land after the appointment
    if allowed > now:
        raise jobs.Reschedule(allowed, "quiet_hours")
    doctor = await s.get(Doctor, appt.doctor_id)
    lang = await messaging.preferred_language(s, clinic, appt.booked_by_phone)
    params = {
        "clinic": clinic.name,
        "doctor": doctor.name if doctor else "",
        "date": fmt_date(appt.slot_start, tz, lang),
        "time": fmt_time(appt.slot_start, tz),
    }
    ids = [f"confirm:{appt.id}", f"act:r|{appt.id}", f"act:c|{appt.id}"]
    titles = [t("btn_confirm", lang), t("btn_reschedule", lang), t("btn_cancel", lang)]
    await messaging.queue_message(
        s,
        clinic_id=clinic.id,
        to_phone=appt.booked_by_phone,
        phone_number_id="",
        category="reminder",
        key=f"reminder_msg:{appt.id}:{jc.job.payload['kind']}",
        run_at=now,
        session={
            "type": "buttons",
            "text": t("reminder", lang, **params),
            "buttons": [{"id": i, "title": ti} for i, ti in zip(ids, titles, strict=True)],
        },
        template={**template_ref("appointment_reminder", lang, **params), "quick_replies": ids},
        patient_id=appt.patient_id,
    )


jobs.handler("reminder.send")(send_reminder)
