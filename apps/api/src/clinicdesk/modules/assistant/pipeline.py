"""Inbound WhatsApp processing (job `wa.inbound`).

webhook → inbound_events (deduplicated) → this job → clinic resolution → one tenant transaction:
  inbound message row (unique provider id ⇒ a retried job never handles a message twice)
  → conversation lock (serialises messages from one patient) → Turn → outbox rows → commit
  → live signals + immediate wake-up of the send jobs.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from clinicdesk.core.logging import log, mask_phone
from clinicdesk.modules.assistant import text as nlu
from clinicdesk.modules.assistant.flows import Turn
from clinicdesk.modules.jobs import service as jobs
from clinicdesk.modules.messaging import service as messaging
from clinicdesk.modules.messaging.models import Conversation, InboundEvent, Message
from clinicdesk.modules.tenancy.models import Clinic


def extract(msg: dict[str, Any]) -> tuple[str | None, str | None, str]:
    """(text, payload_id, kind) from a Cloud API message object."""
    kind = msg.get("type", "unknown")
    if kind == "text":
        return msg.get("text", {}).get("body"), None, "text"
    if kind == "interactive":
        inter = msg.get("interactive", {})
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        return reply.get("title"), reply.get("id"), "interactive"
    if kind == "button":  # quick-reply on a template message
        btn = msg.get("button", {})
        return btn.get("text"), btn.get("payload"), "button"
    if kind in ("audio", "voice"):
        return None, None, "audio"
    return None, None, kind


async def _resolve_clinic(jc: jobs.JobContext, ev: InboundEvent, phone: str, text: str | None) -> Clinic | None:
    s, settings = jc.s, jc.rt.settings  # bypass session: resolution spans tenants
    if ev.phone_number_id and ev.phone_number_id != settings.whatsapp_shared_phone_number_id:
        return await s.scalar(select(Clinic).where(Clinic.wa_phone_number_id == ev.phone_number_id))
    code = nlu.clinic_code(text or "")
    if code:
        clinic = await s.scalar(select(Clinic).where(Clinic.slug == code))
        if clinic is not None:
            return clinic
    last = await s.scalar(
        select(Conversation.clinic_id)
        .where(Conversation.phone == phone, Conversation.phone_number_id == ev.phone_number_id)
        .order_by(Conversation.last_inbound_at.desc().nulls_last())
        .limit(1)
    )
    return await s.get(Clinic, last) if last else None


async def handle_inbound(jc: jobs.JobContext) -> None:
    s, rt = jc.s, jc.rt
    ev = await s.scalar(select(InboundEvent).where(InboundEvent.id == jc.job.payload["event_id"]).with_for_update())
    if ev is None or ev.status != "received":
        return
    now = rt.clock.now()
    if ev.kind == "status":
        st = ev.payload["status"]
        errors = st.get("errors") or []
        err = f"{errors[0].get('code')}: {errors[0].get('title')}" if errors else None
        await messaging.apply_status(s, st["id"], st["status"], err)
        ev.status, ev.processed_at = "processed", now
        return

    msg = ev.payload["message"]
    phone = "+" + str(msg["from"]).lstrip("+")
    text, payload_id, kind = extract(msg)
    clinic = await _resolve_clinic(jc, ev, phone, text)
    if clinic is None or clinic.status == "suspended":
        if clinic is None and ev.phone_number_id == rt.settings.whatsapp_shared_phone_number_id:
            await messaging.queue_message(
                s,
                clinic_id=None,
                to_phone=phone,
                phone_number_id=ev.phone_number_id or "",
                category="transactional",
                key=f"clinic_code:{ev.external_id}",
                run_at=now,
                session={
                    "type": "text",
                    "text": "Please send your clinic's code, e.g. #SMILE. "
                    "કૃપા કરીને ક્લિનિકનો કોડ મોકલો. कृपया क्लिनिक का कोड भेजें।",
                },
            )
        ev.status, ev.processed_at = "ignored", now
        ev.error = "unknown clinic" if clinic is None else "clinic suspended"
        log.info("inbound_ignored", reason=ev.error, phone=mask_phone(phone))
        return

    async with rt.db.session(clinic_id=clinic.id) as ts:
        ts.info["unit_of_work"] = True  # services flush; this turn commits once
        conv = await messaging.get_or_create_conversation(ts, clinic.id, phone, ev.phone_number_id)
        inserted = await ts.scalar(
            insert(Message)
            .values(
                clinic_id=clinic.id,
                conversation_id=conv.id,
                direction="in",
                kind=kind,
                body={"text": text, "payload": payload_id},
                provider_message_id=ev.external_id,
                at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["provider_message_id"], index_where=Message.provider_message_id.is_not(None)
            )
            .returning(Message.id)
        )
        if inserted is not None:  # first time we see this message
            conv.last_inbound_at = now
            if conv.phone_number_id is None:
                conv.phone_number_id = ev.phone_number_id
            turn = Turn(ts, rt, clinic, conv, phone, ev.external_id, now)
            await turn.handle(text, payload_id, kind)
            await turn.finish()
        await ts.commit()
        await jobs.flush_after_commit(ts, rt)
    ev.status, ev.processed_at = "processed", now


jobs.handler("wa.inbound")(handle_inbound)
