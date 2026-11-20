"""Deterministic WhatsApp assistant — one inbound message = one atomic turn (ADR-0006).

Order of checks (fixed, safety first):
  STOP/START → emergency → staff mode → consent gate (DP-1) → medical without booking intent →
  button payloads → awaited free-text answers → keyword intents → unclear (menu, then staff).
All actions go through module services (booking, patients, queue) with this clinic's tenant context; every
patient-facing text comes from the reviewed catalogue in `messaging.templates`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core import events
from clinicdesk.core.context import RequestContext
from clinicdesk.core.errors import Conflict, PolicyViolation, SlotTaken
from clinicdesk.core.runtime import Runtime
from clinicdesk.modules.assistant import text as nlu
from clinicdesk.modules.audit import service as audit
from clinicdesk.modules.booking import policy as booking_policy
from clinicdesk.modules.booking import service as booking
from clinicdesk.modules.booking.models import UPCOMING_STATUSES, Appointment
from clinicdesk.modules.booking.schemas import BookIn, CancelIn, RescheduleIn
from clinicdesk.modules.calls import service as calls
from clinicdesk.modules.messaging import service as messaging
from clinicdesk.modules.messaging.models import Conversation, HandoverTicket
from clinicdesk.modules.messaging.templates import NOTICE_VERSION, fmt_date, fmt_time, t, template_ref
from clinicdesk.modules.patients import service as patients
from clinicdesk.modules.patients.models import ConsentEvent, Patient
from clinicdesk.modules.patients.schemas import PatientCreate
from clinicdesk.modules.queue import service as queue
from clinicdesk.modules.queue.models import QueueEntry, QueueSession
from clinicdesk.modules.recall import service as recall_service
from clinicdesk.modules.scheduling import service as scheduling
from clinicdesk.modules.scheduling.models import Doctor, DoctorSession
from clinicdesk.modules.tenancy.models import Clinic
from clinicdesk.modules.tenancy.schemas import ClinicSettings

MAX_SLOT_ROWS = 5  # FR-2.2: offer 3–5 slots
MAX_DAY_ROWS = 7


@dataclass
class Turn:
    s: AsyncSession
    rt: Runtime
    clinic: Clinic
    conv: Conversation
    phone: str
    inbound_id: str
    now: datetime
    lang: str = "en"
    _n: int = 0
    state: dict[str, Any] = field(default_factory=dict)

    # ----------------------------------------------------------------- helpers
    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.clinic.timezone)

    @property
    def rules(self) -> ClinicSettings:
        return ClinicSettings.from_stored(self.clinic.settings)

    def ctx(self, patient_id: uuid.UUID | None = None) -> RequestContext:
        return RequestContext("patient", patient_id, self.clinic.id, None, "whatsapp")

    def common(self) -> dict[str, Any]:
        return {
            "clinic": self.clinic.name,
            "clinic_phone": self.clinic.phone or "-",
            "address": self.clinic.address or "",
            "map_url": self.clinic.map_url or "",
            "privacy_url": self.rt.settings.privacy_notice_url,
        }

    async def send(
        self,
        session: dict[str, Any],
        *,
        to: str | None = None,
        template: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> None:
        self._n += 1
        await messaging.queue_message(
            self.s,
            clinic_id=self.clinic.id,
            to_phone=to or self.phone,
            phone_number_id=messaging.sender_number(self.clinic, self.rt.settings),
            category="transactional",
            key=key or f"reply:{self.inbound_id}:{self._n}",
            run_at=self.now,  # order within the turn comes from scheduled_jobs.seq
            session=session,
            template=template,
            conversation_id=self.conv.id if to is None else None,
        )

    async def say(self, key: str, **params: Any) -> None:
        await self.send({"type": "text", "text": t(key, self.lang, **self.common(), **params)})

    async def buttons(self, body: str, buttons: list[tuple[str, str]]) -> None:
        await self.send({"type": "buttons", "text": body, "buttons": [{"id": i, "title": ti} for i, ti in buttons]})

    async def listing(self, body: str, button: str, rows: list[dict[str, str]]) -> None:
        await self.send({"type": "list", "text": body, "button": button, "rows": rows})

    def set_state(self, **kw: Any) -> None:
        self.state = {k: v for k, v in kw.items() if v is not None}

    async def phone_patients(self) -> list[Patient]:
        return await messaging.patients_for_phone(self.s, self.clinic.id, self.phone)

    # ----------------------------------------------------------------- entry
    async def handle(self, text: str | None, payload: str | None, kind: str) -> None:
        self.state = dict(self.conv.state or {})
        raw = text or ""
        if text and not payload:
            detected, strong = nlu.detect_language(text, default=self.conv.language or self.clinic.languages[0])
            if strong or not self.conv.language:
                self.lang = detected
            else:
                self.lang = self.conv.language
        else:
            self.lang = self.conv.language or (self.clinic.languages[0] if self.clinic.languages else "en")
        self.conv.language = self.lang

        if text and nlu.is_stop(text):
            return await self.opt_out()
        if text and nlu.is_start(text):
            return await self.opt_in()
        if text and nlu.classify_safety(text) == "emergency":
            return await self.emergency()
        if self.conv.mode == "staff":
            events.emit(
                self.s,
                events.clinic_channel(self.clinic.id),
                {"type": "inbox.message", "conversation_id": self.conv.id},
            )
            return None
        if kind == "audio":
            await self.say("voice_unsupported")
            return await self.menu()

        if payload and payload.startswith("mccb:"):
            # "Call me back" uses only the number the patient called from; no booking data → no consent gate.
            return await self.on_payload(payload)
        if not await self.has_booking_consent():
            return await self.consent_gate(raw, payload)
        if text and not payload and nlu.classify_safety(text) == "medical" and nlu.detect_intent(text) != "book":
            await self.say("medical_deferral")
            return await self.handover("medical")
        if payload:
            return await self.on_payload(payload)
        return await self.on_text(raw)

    async def finish(self) -> None:
        self.conv.state = self.state

    # ----------------------------------------------------------------- consent (DP-1, DP-2)
    async def has_booking_consent(self) -> bool:
        if self.conv.consent_booking_at is not None:
            return True
        granted = await self.s.scalar(
            select(ConsentEvent.at)
            .join(Patient, Patient.id == ConsentEvent.patient_id)
            .where(
                Patient.clinic_id == self.clinic.id,
                Patient.phone == self.phone,
                ConsentEvent.purpose == "booking",
                ConsentEvent.granted.is_(True),
            )
            .limit(1)
        )
        if granted is not None:
            self.conv.consent_booking_at = granted
            return True
        return False

    async def consent_gate(self, raw: str, payload: str | None) -> None:
        if payload == "consent:yes":
            self.conv.consent_booking_at = self.now
            self.conv.consent_notice_version = NOTICE_VERSION
            audit.record(
                self.s,
                self.ctx(),
                "consent.booking_granted",
                "conversation",
                self.conv.id,
                after={"notice_version": NOTICE_VERSION},
            )
            pending = self.state.pop("pending_text", None)
            pending_payload = self.state.pop("pending_payload", None)
            for p in await self.phone_patients():
                await self.record_consent(p.id, "booking", True)
            if pending_payload:  # e.g. "Book" tapped on a missed-call offer before consenting
                return await self.on_payload(pending_payload)
            return await (self.on_text(pending) if pending else self.menu())
        if payload == "consent:no":
            self.state = {}
            audit.record(self.s, self.ctx(), "consent.booking_declined", "conversation", self.conv.id)
            return await self.say("consent_declined")
        if payload and not payload.startswith("consent:"):
            self.state["pending_payload"] = payload[:200]
        elif raw and nlu.detect_intent(raw) not in ("greeting", "none"):
            self.state["pending_text"] = raw[:500]
        await self.buttons(
            t("consent_notice", self.lang, **self.common()),
            [("consent:yes", t("btn_agree", self.lang)), ("consent:no", t("btn_decline", self.lang))],
        )

    async def record_consent(self, patient_id: uuid.UUID, purpose: str, granted: bool) -> None:
        at = self.conv.consent_booking_at if purpose == "booking" and self.conv.consent_booking_at else self.now
        self.s.add(
            ConsentEvent(
                clinic_id=self.clinic.id,
                patient_id=patient_id,
                purpose=purpose,
                granted=granted,
                channel="whatsapp",
                notice_version=NOTICE_VERSION,
                at=at,
            )
        )

    # ----------------------------------------------------------------- opt-out (FR-2.9, AC-9)
    async def opt_out(self) -> None:
        self.conv.opted_out_at = self.now
        for p in await self.phone_patients():
            p.opted_out_at = self.now
            await self.record_consent(p.id, "reminders", False)
            await self.record_consent(p.id, "recalls", False)
        audit.record(self.s, self.ctx(), "consent.opt_out", "conversation", self.conv.id)
        self.state = {}
        await self.say("opted_out")

    async def opt_in(self) -> None:
        self.conv.opted_out_at = None
        for p in await self.phone_patients():
            p.opted_out_at = None
            await self.record_consent(p.id, "reminders", True)
            await self.record_consent(p.id, "recalls", True)
        audit.record(self.s, self.ctx(), "consent.opt_in", "conversation", self.conv.id)
        await self.say("opted_in")

    # ----------------------------------------------------------------- safety & handover (FR-2.6, FR-8.x)
    async def emergency(self) -> None:
        await self.say("emergency")
        await self.handover("emergency")

    async def handover(self, reason: str) -> None:
        await self.s.execute(
            insert(HandoverTicket)
            .values(clinic_id=self.clinic.id, conversation_id=self.conv.id, reason=reason, opened_at=self.now)
            .on_conflict_do_nothing(index_elements=["conversation_id"], index_where=HandoverTicket.status == "open")
        )
        self.conv.mode = "staff"
        self.state = {}
        audit.record(self.s, self.ctx(), "inbox.handover", "conversation", self.conv.id, after={"reason": reason})
        events.emit(
            self.s,
            events.clinic_channel(self.clinic.id),
            {"type": "inbox.emergency" if reason == "emergency" else "inbox.updated", "conversation_id": self.conv.id},
        )
        if reason == "emergency" and self.clinic.phone and self.clinic.phone != self.phone:
            link = f"{self.rt.settings.public_base_url}/inbox/{self.conv.id}"
            params = {"reason": "EMERGENCY", "phone": self.phone, "link": link}
            await self.send(
                {"type": "text", "text": t("staff_alert", "en", **params)},
                to=self.clinic.phone,
                template=template_ref("staff_alert", "en", **params),
                key=f"staff_alert:{self.inbound_id}",
            )
        if reason not in ("emergency", "medical"):
            await self.say("handover_ack")

    # ----------------------------------------------------------------- menu & routing
    async def menu(self) -> None:
        self.state = {}
        rows = [
            ("menu:book", "row_book"),
            ("menu:manage", "row_manage"),
            ("menu:token", "row_token"),
            ("menu:queue", "row_queue"),
            ("menu:info", "row_info"),
            ("menu:staff", "row_staff"),
        ]
        await self.listing(
            t("menu", self.lang), t("menu_button", self.lang), [{"id": i, "title": t(k, self.lang)} for i, k in rows]
        )

    async def on_text(self, raw: str) -> None:
        step = self.state.get("step")
        if step == "ask_name":
            return await self.got_name(raw)
        if step == "ask_age":
            return await self.got_age(raw)
        intent = nlu.detect_intent(raw)
        today = self.now.astimezone(self.tz).date()
        if intent == "book":
            self.state["unclear"] = 0
            return await self.start_book(day=nlu.parse_date_hint(raw, today), tod=nlu.parse_time_of_day(raw))
        handlers: dict[str, Callable[[], Awaitable[None]]] = {
            "greeting": self.menu,
            "manage": self.manage,
            "token": self.token,
            "queue": self.queue_status,
            "info": self.info,
            "staff": lambda: self.handover("requested"),
        }
        if intent in handlers:
            return await handlers[intent]()
        day = nlu.parse_date_hint(raw, today)
        if day is not None:  # "kal" alone after a menu → booking for that day
            return await self.start_book(day=day, tod=nlu.parse_time_of_day(raw))
        unclear = int(self.state.get("unclear", 0)) + 1
        if unclear >= 2:
            return await self.handover("unclear")
        await self.say("unknown")
        await self.menu()
        self.state["unclear"] = unclear

    async def on_payload(self, payload: str) -> None:
        head, _, rest = payload.partition(":")
        try:
            if head == "menu":
                menu_actions: dict[str, Callable[[], Awaitable[None]]] = {
                    "book": self.start_book,
                    "manage": self.manage,
                    "token": self.token,
                    "queue": self.queue_status,
                    "info": self.info,
                    "staff": lambda: self.handover("requested"),
                }
                return await menu_actions.get(rest, self.menu)()
            if head == "doc":
                return await self.picked_doctor(uuid.UUID(rest))
            if head == "days":
                return await self.offer_days(uuid.UUID(self.state["doctor_id"]))
            if head == "day":
                return await self.offer_slots(uuid.UUID(self.state["doctor_id"]), date.fromisoformat(rest), None)
            if head == "slot":
                doctor_id, _, iso = rest.partition("|")
                return await self.picked_slot(uuid.UUID(doctor_id), datetime.fromisoformat(iso))
            if head == "pat":
                return await self.picked_patient(rest)
            if head == "appt":
                return await self.picked_appointment(uuid.UUID(rest))
            if head == "act":
                action, _, appt_id = rest.partition("|")
                return await self.appointment_action(action, uuid.UUID(appt_id))
            if head == "rem":
                return await self.reminders_answer(rest == "yes")
            if head == "mc":
                return await self.start_book(source="missed_call", source_ref=rest)
            if head == "mccb":
                if await calls.caller_requested_callback(self.s, self.ctx(), uuid.UUID(rest), self.phone):
                    self.state = {}
                    return await self.say("callback_ack")
                return await self.menu()
            if head == "confirm":
                return await self.confirm_appointment(uuid.UUID(rest))
            if head == "recall":
                return await self.recall_book(uuid.UUID(rest))
            if head == "recall_no":
                return await self.recall_decline(uuid.UUID(rest))
            if head == "rebook":
                return await self.start_book(source="noshow_rebook", source_ref=rest)
        except (KeyError, ValueError):
            pass  # stale or forged payload → fall through to the menu
        await self.menu()

    # ----------------------------------------------------------------- booking (FR-2.1..2.4)
    async def active_doctors(self) -> list[Doctor]:
        rows = await self.s.scalars(
            select(Doctor).where(Doctor.clinic_id == self.clinic.id, Doctor.is_active.is_(True)).order_by(Doctor.name)
        )
        return list(rows.all())

    async def start_book(
        self,
        day: date | None = None,
        tod: str | None = None,
        flow: str = "book",
        source: str | None = None,
        source_ref: str | None = None,
    ) -> None:
        if source is None and flow == "book":
            open_call = await calls.open_call_for(self.s, self.clinic.id, self.phone, self.now)
            if open_call is not None:  # FR-3.4: a booking soon after a missed call is a recovered call
                source, source_ref = "missed_call", str(open_call.id)
        doctors = await self.active_doctors()
        carry = {
            "flow": flow,
            "day": day.isoformat() if day else None,
            "tod": tod,
            "source": source,
            "source_ref": source_ref,
            "appt_id": self.state.get("appt_id") if flow == "resched" else None,
        }
        if not doctors:
            await self.say("no_days", days=self.rules.booking_horizon_days)
            return await self.handover("no_slots")
        if len(doctors) > 1:
            self.set_state(step="pick_doctor", **carry)
            return await self.listing(
                t("pick_doctor", self.lang),
                t("menu_button", self.lang),
                [{"id": f"doc:{d.id}", "title": d.name} for d in doctors[:10]],
            )
        self.set_state(doctor_id=str(doctors[0].id), **carry)
        await self.offer(doctors[0].id, day, tod)

    async def picked_doctor(self, doctor_id: uuid.UUID) -> None:
        await scheduling.get_doctor(self.s, self.ctx(), doctor_id)  # tenant check
        self.state["doctor_id"] = str(doctor_id)
        if self.state.get("flow") == "token":
            return await self.issue_token(doctor_id)
        day = date.fromisoformat(self.state["day"]) if self.state.get("day") else None
        await self.offer(doctor_id, day, self.state.get("tod"))

    async def offer(self, doctor_id: uuid.UUID, day: date | None, tod: str | None) -> None:
        if day is not None:
            return await self.offer_slots(doctor_id, day, tod)
        await self.offer_days(doctor_id)

    async def offer_days(self, doctor_id: uuid.UUID) -> None:
        today = self.now.astimezone(self.tz).date()
        slots = await scheduling.available_slots(
            self.s, self.ctx(), self.rt.clock, doctor_id, today, today + timedelta(days=self.rules.booking_horizon_days)
        )
        counts: dict[date, int] = {}
        for sl in slots:
            d = sl.start.astimezone(self.tz).date()
            counts[d] = counts.get(d, 0) + 1
        if not counts:
            await self.say("no_days", days=self.rules.booking_horizon_days)
            return await self.handover("no_slots")
        self.state["doctor_id"], self.state["step"] = str(doctor_id), "pick_day"
        rows = []
        for d, n in list(counts.items())[:MAX_DAY_ROWS]:
            anchor = next(sl.start for sl in slots if sl.start.astimezone(self.tz).date() == d)
            rows.append(
                {"id": f"day:{d.isoformat()}", "title": fmt_date(anchor, self.tz, self.lang), "description": f"{n} ✓"}
            )
        await self.listing(t("pick_date", self.lang), t("days_button", self.lang), rows)

    async def offer_slots(self, doctor_id: uuid.UUID, day: date, tod: str | None, intro: str | None = None) -> None:
        slots = await scheduling.available_slots(self.s, self.ctx(), self.rt.clock, doctor_id, day, day)
        preferred = [sl for sl in slots if nlu.matches_time_of_day(sl.start.astimezone(self.tz).hour, tod)]  # type: ignore[arg-type]
        chosen = (preferred or slots)[:MAX_SLOT_ROWS]
        self.state["doctor_id"], self.state["day"], self.state["step"] = str(doctor_id), day.isoformat(), "pick_slot"
        if not chosen:
            label = fmt_date(datetime.combine(day, datetime.min.time(), tzinfo=self.tz), self.tz, self.lang)
            await self.say("no_slots", date=label)
            return await self.offer_days(doctor_id)
        label = fmt_date(chosen[0].start, self.tz, self.lang)
        rows = [
            {"id": f"slot:{doctor_id}|{sl.start.isoformat()}", "title": fmt_time(sl.start, self.tz)} for sl in chosen
        ]
        rows.append({"id": "days:", "title": t("row_other_day", self.lang)})  # keeps the current flow
        body = (intro + "\n" if intro else "") + t("pick_slot", self.lang, date=label)
        await self.listing(body, t("times_button", self.lang), rows)

    async def picked_slot(self, doctor_id: uuid.UUID, start: datetime) -> None:
        self.state.update(doctor_id=str(doctor_id), slot=start.isoformat())
        if self.state.get("flow") == "resched" and self.state.get("appt_id"):
            return await self.do_reschedule(uuid.UUID(self.state["appt_id"]), doctor_id, start)
        people = await self.phone_patients()
        if not people:
            self.state["step"] = "ask_name"
            return await self.say("ask_name")
        if len(people) == 1:
            return await self.do_book(people[0], doctor_id, start)
        self.state["step"] = "pick_patient"
        rows = [{"id": f"pat:{p.id}", "title": p.name} for p in people[:9]]
        rows.append({"id": "pat:new", "title": t("row_someone_else", self.lang)})
        await self.listing(t("which_patient", self.lang), t("patients_button", self.lang), rows)

    async def picked_patient(self, value: str) -> None:
        if value == "new":
            self.state["step"] = "ask_name"
            return await self.say("ask_name")
        patient = next((p for p in await self.phone_patients() if str(p.id) == value), None)
        if patient is None or "slot" not in self.state:
            return await self.menu()
        await self.do_book(patient, uuid.UUID(self.state["doctor_id"]), datetime.fromisoformat(self.state["slot"]))

    async def got_name(self, raw: str) -> None:
        name = nlu.clean_name(raw)
        if name is None:
            return await self.say("ask_name")
        self.state.update(name=name, step="ask_age")
        await self.say("ask_age")

    async def got_age(self, raw: str) -> None:
        age = nlu.parse_age(raw)
        if age is None or "slot" not in self.state:
            return await self.say("bad_age")
        people = await self.phone_patients()
        holder = people[0].id if people else None
        try:
            patient = await patients.create_patient(
                self.s,
                self.ctx(),
                PatientCreate(
                    phone=self.phone,
                    name=self.state["name"],
                    age=age,
                    language=self.lang if self.lang in ("gu", "hi", "en") else None,
                    account_holder_id=holder,
                ),
            )
        except Conflict:  # same name + number already exists → reuse that record
            patient = next(p for p in await self.phone_patients() if p.name == self.state["name"])
        await self.record_consent(patient.id, "booking", True)
        await self.do_book(patient, uuid.UUID(self.state["doctor_id"]), datetime.fromisoformat(self.state["slot"]))

    async def do_book(self, patient: Patient, doctor_id: uuid.UUID, start: datetime) -> None:
        source = self.state.get("source") or "staff"
        ref = self.state.get("source_ref")
        try:
            appt = await booking.book(
                self.s,
                self.ctx(patient.id),
                self.rt.clock,
                BookIn(
                    doctor_id=doctor_id,
                    patient_id=patient.id,
                    slot_start=start,
                    source=source,
                    source_ref_id=uuid.UUID(ref) if ref else None,
                ),
            )
        except SlotTaken:
            day = start.astimezone(self.tz).date()
            return await self.offer_slots(doctor_id, day, None, intro=t("slot_taken", self.lang))
        except PolicyViolation as e:
            return await self.policy_reply(e)
        await self.confirm_booked(appt, patient)

    async def confirm_booked(self, appt: Appointment, patient: Patient) -> None:
        doctor = await self.s.get(Doctor, appt.doctor_id)
        self.state = {}
        await self.say(
            "booked",
            doctor=doctor.name if doctor else "",
            date=fmt_date(appt.slot_start, self.tz, self.lang),
            time=fmt_time(appt.slot_start, self.tz),
        )
        asked = await self.s.scalar(
            select(ConsentEvent.id).where(ConsentEvent.patient_id == patient.id, ConsentEvent.purpose == "reminders")
        )
        if asked is None and self.conv.opted_out_at is None:
            await self.buttons(
                t("ask_reminders", self.lang, **self.common()),
                [("rem:yes", t("btn_yes", self.lang)), ("rem:no", t("btn_no", self.lang))],
            )

    async def reminders_answer(self, granted: bool) -> None:
        for p in await self.phone_patients():
            await self.record_consent(p.id, "reminders", granted)
            await self.record_consent(p.id, "recalls", granted)
        audit.record(
            self.s,
            self.ctx(),
            "consent.reminders_" + ("granted" if granted else "declined"),
            "conversation",
            self.conv.id,
        )
        await self.say("reminders_on" if granted else "reminders_off")

    async def policy_reply(self, e: PolicyViolation) -> None:
        self.state = {}
        if e.code == "max_upcoming_reached":
            return await self.say("limit_reached", limit=self.rules.max_upcoming_per_doctor)
        if e.code == "change_cutoff_passed":
            return await self.say("too_late_change", minutes=self.rules.change_cutoff_minutes)
        await self.say("cannot_book")

    # ----------------------------------------------------------------- manage (FR-2.4, AC-4)
    async def my_upcoming(self) -> list[Appointment]:
        ids = [p.id for p in await self.phone_patients()]
        if not ids:
            return []
        rows = await self.s.scalars(
            select(Appointment)
            .where(
                Appointment.patient_id.in_(ids),
                Appointment.status.in_(UPCOMING_STATUSES),
                Appointment.slot_start > self.now,
            )
            .order_by(Appointment.slot_start)
            .limit(10)
        )
        return list(rows.all())

    async def manage(self) -> None:
        appts = await self.my_upcoming()
        if not appts:
            return await self.say("no_appointments")
        if len(appts) == 1:
            return await self.picked_appointment(appts[0].id)
        doctors = {d.id: d.name for d in await self.active_doctors()}
        rows = [
            {
                "id": f"appt:{a.id}",
                "title": f"{fmt_date(a.slot_start, self.tz, self.lang)} {fmt_time(a.slot_start, self.tz)}",
                "description": doctors.get(a.doctor_id, ""),
            }
            for a in appts
        ]
        await self.listing(t("pick_appointment", self.lang), t("patients_button", self.lang), rows)

    async def owned(self, appt_id: uuid.UUID) -> Appointment | None:
        return next((a for a in await self.my_upcoming() if a.id == appt_id), None)

    async def picked_appointment(self, appt_id: uuid.UUID) -> None:
        appt = await self.owned(appt_id)
        if appt is None:
            return await self.menu()
        doctor = await self.s.get(Doctor, appt.doctor_id)
        body = t(
            "manage_actions",
            self.lang,
            doctor=doctor.name if doctor else "",
            date=fmt_date(appt.slot_start, self.tz, self.lang),
            time=fmt_time(appt.slot_start, self.tz),
        )
        await self.buttons(
            body,
            [(f"act:r|{appt.id}", t("btn_reschedule", self.lang)), (f"act:c|{appt.id}", t("btn_cancel", self.lang))],
        )

    async def appointment_action(self, action: str, appt_id: uuid.UUID) -> None:
        appt = await self.owned(appt_id)
        if appt is None:
            return await self.menu()
        try:
            booking_policy.check_changeable(appt.slot_start, now=self.now, rules=self.rules)
        except PolicyViolation as e:
            return await self.policy_reply(e)
        if action == "c":
            try:
                await booking.cancel(self.s, self.ctx(appt.patient_id), self.rt.clock, appt.id, CancelIn())
            except PolicyViolation as e:
                return await self.policy_reply(e)
            self.state = {}
            return await self.say(
                "cancelled", date=fmt_date(appt.slot_start, self.tz, self.lang), time=fmt_time(appt.slot_start, self.tz)
            )
        self.set_state(flow="resched", appt_id=str(appt.id), doctor_id=str(appt.doctor_id))
        await self.offer_days(appt.doctor_id)

    async def do_reschedule(self, appt_id: uuid.UUID, doctor_id: uuid.UUID, start: datetime) -> None:
        appt = await self.owned(appt_id)
        if appt is None:
            return await self.menu()
        try:
            new = await booking.reschedule(
                self.s,
                self.ctx(appt.patient_id),
                self.rt.clock,
                appt.id,
                RescheduleIn(slot_start=start, doctor_id=doctor_id),
            )
        except SlotTaken:
            return await self.offer_slots(
                doctor_id, start.astimezone(self.tz).date(), None, intro=t("slot_taken", self.lang)
            )
        except PolicyViolation as e:
            return await self.policy_reply(e)
        patient = await self.s.get(Patient, new.patient_id)
        assert patient is not None
        await self.confirm_booked(new, patient)

    # ----------------------------------------------------------------- reminders & recalls (FR-5.1, FR-6.3)
    async def confirm_appointment(self, appt_id: uuid.UUID) -> None:
        appt = await self.owned(appt_id)
        if appt is None:
            return await self.menu()
        if appt.status == "booked":
            await booking.set_status(self.s, self.ctx(appt.patient_id), self.rt.clock, appt.id, "confirmed")
        self.state = {}
        await self.say("confirmed_ack")

    async def recall_book(self, recall_id: uuid.UUID) -> None:
        r = await recall_service.recall_for_phone(self.s, self.clinic.id, self.phone, recall_id)
        if r is None or r.status not in ("scheduled", "sent"):
            return await self.start_book()
        doctor = await self.s.get(Doctor, r.doctor_id)
        if doctor is None or not doctor.is_active:
            return await self.start_book(source="recall", source_ref=str(r.id))
        self.set_state(flow="book", source="recall", source_ref=str(r.id), doctor_id=str(r.doctor_id))
        await self.offer_days(r.doctor_id)

    async def recall_decline(self, recall_id: uuid.UUID) -> None:
        r = await recall_service.recall_for_phone(self.s, self.clinic.id, self.phone, recall_id)
        if r is not None:
            await recall_service.decline(self.s, self.ctx(r.patient_id), r)
        self.state = {}
        await self.say("recall_declined")

    # ----------------------------------------------------------------- queue (FR-4.1..4.3)
    async def token(self) -> None:
        doctors = await self.active_doctors()
        if len(doctors) == 1:
            return await self.issue_token(doctors[0].id)
        self.set_state(flow="token", step="pick_doctor")
        await self.listing(
            t("pick_doctor", self.lang),
            t("menu_button", self.lang),
            [{"id": f"doc:{d.id}", "title": d.name} for d in doctors[:10]],
        )

    async def issue_token(self, doctor_id: uuid.UUID) -> None:
        people = await self.phone_patients()
        try:
            entry = await queue.issue_token(
                self.s,
                self.ctx(people[0].id if len(people) == 1 else None),
                self.rt.clock,
                doctor_id=doctor_id,
                patient_id=people[0].id if len(people) == 1 else None,
                phone=self.phone,
                channel="whatsapp",
            )
        except PolicyViolation as e:
            self.state = {}
            if e.code == "token_window_not_open":
                return await self.say("token_not_open", minutes=self.rules.token_window_minutes)
            return await self.say("token_closed")
        self.state = {}
        await self.reply_entry_status(entry, "token_issued")

    async def reply_entry_status(self, entry: QueueEntry, key: str) -> None:
        qs = await self.s.get(QueueSession, entry.queue_session_id)
        assert qs is not None
        snap = await queue.build_snapshot(self.s, qs, self.now)
        view = next(v for v in snap.entries if v.entry.id == entry.id)
        ahead = view.ahead or 0
        wait = int(((view.eta or self.now) - self.now).total_seconds() // 60)
        if ahead <= self.rules.alert_ahead and entry.alert_sent_at is None:
            entry.alert_sent_at = self.now  # this reply already tells them; no separate FR-4.3 alert
        doctor = await self.s.get(Doctor, qs.doctor_id)
        await self.say(
            key,
            token=entry.token_no,
            doctor=doctor.name if doctor else "",
            ahead=ahead,
            wait=max(wait, 0),
            current=snap.current.token_no if snap.current else "-",
            link=f"{self.rt.settings.public_base_url}/t/{entry.public_code}",
        )

    async def queue_status(self) -> None:
        today = self.now.astimezone(self.tz).date()
        entry = await self.s.scalar(
            select(QueueEntry)
            .join(QueueSession, QueueSession.id == QueueEntry.queue_session_id)
            .where(
                QueueEntry.phone == self.phone,
                QueueEntry.status.in_(("waiting", "called")),
                QueueSession.session_date == today,
            )
            .order_by(QueueEntry.issued_at.desc())
            .limit(1)
        )
        if entry is None:
            return await self.say("no_token")
        await self.reply_entry_status(entry, "queue_status")

    # ----------------------------------------------------------------- FAQ (FR-2.5)
    async def info(self) -> None:
        rows = await self.s.execute(
            select(Doctor.name, DoctorSession.weekday, DoctorSession.start_time, DoctorSession.end_time)
            .join(DoctorSession, DoctorSession.doctor_id == Doctor.id)
            .where(Doctor.clinic_id == self.clinic.id, Doctor.is_active.is_(True))
            .order_by(Doctor.name, DoctorSession.weekday, DoctorSession.start_time)
        )
        from clinicdesk.modules.messaging.templates import WEEKDAYS

        by_doc: dict[str, dict[str, list[str]]] = {}
        for name, weekday, start, end in rows.all():
            span = f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
            by_doc.setdefault(name, {}).setdefault(span, []).append(WEEKDAYS[self.lang][weekday])
        lines = [
            f"{name}: " + "; ".join(f"{', '.join(days)} {span}" for span, days in spans.items())
            for name, spans in by_doc.items()
        ]
        fee = self.clinic.default_fee_paise // 100
        await self.say("clinic_info", timings="\n".join(lines) or "-", fee=fee)
