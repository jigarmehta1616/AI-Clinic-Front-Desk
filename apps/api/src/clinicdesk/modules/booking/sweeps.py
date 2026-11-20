"""No-show sweep (FR-5.2, AC-6): booked/confirmed appointments not marked arrived by the end of their
doctor session (+ clinic grace) become no-shows. Idempotent; safe to run from several workers."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from clinicdesk.core.context import system_context
from clinicdesk.core.runtime import Runtime
from clinicdesk.modules.audit import service as audit
from clinicdesk.modules.booking.models import UPCOMING_STATUSES, Appointment
from clinicdesk.modules.booking.service import snapshot
from clinicdesk.modules.messaging import service as messaging
from clinicdesk.modules.messaging.templates import t, template_ref
from clinicdesk.modules.scheduling.models import DoctorSession
from clinicdesk.modules.scheduling.policy import SessionTemplate, session_window_for
from clinicdesk.modules.tenancy.models import Clinic
from clinicdesk.modules.tenancy.schemas import ClinicSettings

LOOKBACK = timedelta(days=2)


async def noshow_sweep(rt: Runtime) -> int:
    db, now = rt.db, rt.clock.now()
    # Discover candidates across tenants (ids only), then act per clinic under RLS.
    async with db.session(bypass_rls=True) as s:
        rows = await s.execute(
            select(Appointment.clinic_id, Appointment.id).where(
                Appointment.status.in_(UPCOMING_STATUSES),
                Appointment.slot_end <= now,
                Appointment.slot_end > now - LOOKBACK,
            )
        )
        by_clinic: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for clinic_id, appt_id in rows.all():
            by_clinic[clinic_id].append(appt_id)

    marked = 0
    for clinic_id, ids in by_clinic.items():
        ctx = system_context(clinic_id)
        async with db.session(clinic_id=clinic_id) as s:
            clinic = await s.get(Clinic, clinic_id)
            if clinic is None:
                continue
            tz = ZoneInfo(clinic.timezone)
            grace = timedelta(minutes=ClinicSettings.from_stored(clinic.settings).noshow_grace_minutes)
            appts = (
                await s.scalars(select(Appointment).where(Appointment.id.in_(ids)).with_for_update(skip_locked=True))
            ).all()
            templates: dict[uuid.UUID, list[SessionTemplate]] = {}
            for appt in appts:
                if appt.status not in UPCOMING_STATUSES:
                    continue  # changed since discovery
                if appt.doctor_id not in templates:
                    rows2 = await s.scalars(select(DoctorSession).where(DoctorSession.doctor_id == appt.doctor_id))
                    templates[appt.doctor_id] = [
                        SessionTemplate(x.weekday, x.start_time, x.end_time) for x in rows2.all()
                    ]
                window = session_window_for(templates[appt.doctor_id], at=appt.slot_start, tz=tz)
                session_end = window[1] if window else appt.slot_end  # session edited since booking
                if now < session_end + grace:
                    continue
                before = snapshot(appt)
                appt.status = "no_show"
                audit.record(
                    s,
                    ctx,
                    "appointment.no_show",
                    "appointment",
                    appt.id,
                    before=before,
                    after={**snapshot(appt), "reason": "not_arrived_by_session_end"},
                )
                marked += 1
                await _queue_rebook(s, clinic, appt, now)  # FR-5.3
            await s.commit()
    return marked


async def _queue_rebook(s, clinic: Clinic, appt: Appointment, now) -> None:  # type: ignore[no-untyped-def]
    """Same-day rebooking offer. Category `reminder`: quiet hours defer it to 08:00 (BR-7), and it is
    skipped at dispatch if the patient opted out or never consented to reminders (BR-8, DP-2)."""
    lang = await messaging.preferred_language(s, clinic, appt.booked_by_phone)
    payload_id = f"rebook:{appt.id}"
    await messaging.queue_message(
        s,
        clinic_id=clinic.id,
        to_phone=appt.booked_by_phone,
        phone_number_id="",
        category="reminder",
        key=f"noshow_rebook:{appt.id}",
        run_at=now,
        session={
            "type": "buttons",
            "text": t("noshow_rebook", lang, clinic=clinic.name),
            "buttons": [{"id": payload_id, "title": t("btn_book_again", lang)}],
        },
        template={**template_ref("noshow_rebook", lang, clinic=clinic.name), "quick_replies": [payload_id]},
        patient_id=appt.patient_id,
    )
