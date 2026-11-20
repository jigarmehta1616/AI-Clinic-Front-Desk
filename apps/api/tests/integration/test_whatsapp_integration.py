"""WhatsApp end-to-end on real PostgreSQL with a fake Meta client.

AC-1, AC-2 (chat), AC-4, AC-6 (rebook), AC-8, AC-9, FR-2.x, FR-4.3, FR-5.3, FR-8.x, BR-7, BR-9, DP-1, DP-2, NFR-4.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from tests.conftest import rand_phone
from tests.integration.wa import Chat, consent, wa_clinic  # noqa: F401  (fixture)

from clinicdesk.integrations.whatsapp import TransientSendError, option_ids, text_of
from clinicdesk.modules.booking.sweeps import noshow_sweep
from clinicdesk.modules.jobs import service as jobs
from clinicdesk.modules.messaging import service as messaging
from clinicdesk.modules.messaging.models import HandoverTicket, OutboxMessage
from clinicdesk.modules.patients.models import ConsentEvent, Patient

pytestmark = pytest.mark.integration
IST = ZoneInfo("Asia/Kolkata")


def at(hh: int, mm: int = 0, day: int = 0) -> datetime:
    return datetime.combine(date(2026, 11, 23) + timedelta(days=day), time(hh, mm), tzinfo=IST).astimezone(UTC)


# ---------------------------------------------------------------------------------------------------------------
async def test_webhook_rejects_bad_signature_and_verifies_subscription(client, rt, whatsapp, wa_clinic):
    fx = await wa_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    assert await chat.post(chat.envelope(chat.msg("hi")), sign=False) == 401
    r = await client.get(
        "/api/v1/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"},
    )
    assert r.status_code == 200 and r.text == "42"
    r = await client.get(
        "/api/v1/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"},
    )
    assert r.status_code == 403


async def test_duplicate_webhook_delivery_handled_once(client, rt, whatsapp, wa_clinic):
    """NFR-4: Meta redelivers; the patient gets one reply set."""
    fx = await wa_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    env = chat.envelope(chat.msg("hi", mid="wamid.dup.1" + uuid.uuid4().hex))
    assert await chat.post(env) == 200 and await chat.post(env) == 200
    await asyncio.gather(jobs.drain(rt), jobs.drain(rt))
    assert len(whatsapp.to(chat.phone)) == 1  # one consent notice


async def test_ac1_new_patient_books_kal_savare_in_six_messages(client, rt, whatsapp, wa_clinic, database):
    """AC-1, FR-2.1/2.2/2.3, DP-1, DP-2, BR-13: 'appointment kal savare' → tomorrow-morning slots → booked."""
    fx = await wa_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    first = await chat.send("appointment kal savare")
    assert option_ids(first[-1]) == ["consent:yes", "consent:no"]
    assert "https://clinicdesk.test/privacy" in text_of(first[-1])  # DP-1 notice link, any language
    slots = await chat.send(reply="consent:yes")
    ids = option_ids(slots[-1])
    slot_ids = [i for i in ids if i.startswith("slot:")]
    assert 3 <= len(slot_ids) <= 5
    starts = [datetime.fromisoformat(i.split("|")[1]) for i in slot_ids]
    assert all(s.astimezone(IST).date() == date(2026, 11, 24) and s.astimezone(IST).hour < 12 for s in starts)
    await chat.send(reply=slot_ids[0])  # → ask name
    await chat.send("Kantaben Patel")  # → ask age
    done = await chat.send("૬૪")  # Gujarati digits
    assert "✅" in text_of(done[0])
    assert option_ids(done[1]) == ["rem:yes", "rem:no"]  # DP-2: separate reminders consent
    replies_until_booked = 1 + len(slots) + 1 + 1 + 1  # consent, slots, ask name, ask age, booked
    assert replies_until_booked <= 6

    day = (await client.get("/api/v1/appointments", params={"day": "2026-11-24"}, headers=fx.h)).json()
    assert len(day) == 1 and day[0]["source"] == "assistant"
    assert datetime.fromisoformat(day[0]["slot_start"]) == starts[0]
    async with database.session(clinic_id=uuid.UUID(fx.clinic_id)) as s:
        p = await s.scalar(select(Patient).where(Patient.phone == chat.phone))
        assert p.name == "Kantaben Patel" and p.age == 64 and p.language in ("gu", "hi", "en")
        purposes = (await s.scalars(select(ConsentEvent.purpose).where(ConsentEvent.patient_id == p.id))).all()
        assert list(purposes) == ["booking"]
    audit = (await client.get("/api/v1/audit", params={"entity_id": day[0]["id"]}, headers=fx.h)).json()
    assert audit[0]["action"] == "appointment.book" and audit[0]["channel"] == "whatsapp"
    assert audit[0]["actor_type"] == "patient"

    await chat.send(reply="rem:yes")
    async with database.session(clinic_id=uuid.UUID(fx.clinic_id)) as s:
        granted = (
            await s.scalars(
                select(ConsentEvent.purpose).where(ConsentEvent.patient_id == p.id, ConsentEvent.granted.is_(True))
            )
        ).all()
        assert sorted(granted) == ["booking", "recalls", "reminders"]


async def test_ac2_two_patients_last_slot_in_chat(client, rt, whatsapp, wa_clinic):
    """AC-2: both tap the same slot; one is booked, the other is offered the next slots."""
    fx = await wa_clinic(patients=0)
    a, b = Chat(client, rt, whatsapp, fx.pnid), Chat(client, rt, whatsapp, fx.pnid)
    offers = [await consent(c, "appointment kal savare") for c in (a, b)]
    slot = [i for i in option_ids(offers[0][-1]) if i.startswith("slot:")][0]
    assert slot in option_ids(offers[1][-1])  # both were offered the same slot
    for c in (a, b):
        await c.send(reply=slot)
        await c.send("Patient " + ("Alpha" if c is a else "Beta"))
    seen = {c.phone: len(whatsapp.to(c.phone)) for c in (a, b)}
    await asyncio.gather(a.post(a.envelope(a.msg("30"))), b.post(b.envelope(b.msg("40"))))
    await asyncio.gather(jobs.drain(rt), jobs.drain(rt))  # both turns race on the same slot
    await jobs.drain(rt)
    ra, rb = (whatsapp.to(c.phone)[seen[c.phone] :] for c in (a, b))
    outcomes = sorted("booked" if "✅" in text_of(x[0]) else "retry" for x in (ra, rb))
    assert outcomes == ["booked", "retry"]
    loser = ra if "✅" not in text_of(ra[0]) else rb
    assert slot not in option_ids(loser[0]) and any(i.startswith("slot:") for i in option_ids(loser[0]))
    day = (await client.get("/api/v1/appointments", params={"day": "2026-11-24"}, headers=fx.h)).json()
    assert len(day) == 1


async def test_ac4_reschedule_from_chat_frees_old_slot(client, rt, whatsapp, wa_clinic):
    """AC-4, FR-2.4: 'reschedule' → pick day/slot → old freed, both audited."""
    fx = await wa_clinic(patients=0)
    chat = Chat(client, rt, whatsapp, fx.pnid)
    out = await consent(chat, "appointment kal savare")
    first_slot = [i for i in option_ids(out[-1]) if i.startswith("slot:")][0]
    await chat.send(reply=first_slot)
    await chat.send("Ramesh Shah")
    await chat.send("51")
    old = (await client.get("/api/v1/appointments", params={"day": "2026-11-24"}, headers=fx.h)).json()[0]

    actions = await chat.send("reschedule")
    assert option_ids(actions[-1]) == [f"act:r|{old['id']}", f"act:c|{old['id']}"]
    days = await chat.send(reply=f"act:r|{old['id']}")
    await chat.send(reply=[i for i in option_ids(days[-1]) if i.startswith("day:2026-11-25")][0])
    slots = whatsapp.to(chat.phone)[-1]
    done = await chat.send(reply=[i for i in option_ids(slots) if i.startswith("slot:")][0])
    assert "✅" in text_of(done[0])
    statuses = {
        a["id"]: a["status"]
        for a in (await client.get("/api/v1/appointments", params={"day": "2026-11-24"}, headers=fx.h)).json()
    }
    assert statuses[old["id"]] == "rescheduled"
    audit = (await client.get("/api/v1/audit", params={"entity_type": "appointment"}, headers=fx.h)).json()
    assert {"appointment.reschedule_from", "appointment.reschedule_to"} <= {a["action"] for a in audit}


@pytest.mark.parametrize("words", ["chest pain", "છાતીમાં દુખાવો થાય છે"])
async def test_ac8_emergency_reply_alert_and_handover(client, rt, whatsapp, wa_clinic, broker, words):
    """AC-8, FR-8.3, BR-10: works even before consent; staff alerted; assistant stops answering."""
    fx = await wa_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    out = await chat.send(words)
    assert len(out) == 1
    body = text_of(out[0])
    assert "108" in body and "112" in body and fx.phone in body
    alert = whatsapp.to(fx.phone)  # clinic phone has no open 24 h window → approved template (BR-9)
    assert len(alert) == 1 and alert[0]["template"]["name"] == "staff_alert"
    params = [p["text"] for p in alert[0]["template"]["components"][0]["parameters"]]
    assert params[0] == "EMERGENCY" and params[1] == chat.phone
    inbox = (await client.get("/api/v1/inbox", headers=fx.h)).json()
    assert [(i["reason"], i["phone"]) for i in inbox] == [("emergency", chat.phone)]
    assert any('"inbox.emergency"' in m for _, m in broker.published)
    assert await chat.send("hello?") == []  # staff mode: no automated answers


async def test_medical_question_goes_to_staff_without_advice(client, rt, whatsapp, wa_clinic):
    """FR-2.6, BR-10."""
    fx = await wa_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    await consent(chat)
    out = await chat.send("which medicine should I take for tooth pain?")
    assert len(out) == 1
    body = text_of(out[0])
    assert any(w in body for w in ("medical advice", "તબીબી સલાહ", "चिकित्सा सलाह"))  # deferral, not advice
    inbox = (await client.get("/api/v1/inbox", headers=fx.h)).json()
    assert [i["reason"] for i in inbox] == ["medical"]


async def test_ac9_stop_blocks_reminders_and_records_opt_out(client, rt, whatsapp, wa_clinic, database):
    """AC-9, FR-2.9, BR-8: STOP → reminder-category messages are skipped at dispatch."""
    fx = await wa_clinic(patients=0)
    chat = Chat(client, rt, whatsapp, fx.pnid)
    out = await consent(chat, "appointment kal savare")
    await chat.send(reply=[i for i in option_ids(out[-1]) if i.startswith("slot:")][0])
    await chat.send("Asha Mehta")
    await chat.send("35")
    await chat.send(reply="rem:yes")
    stopped = await chat.send("STOP")
    assert len(stopped) == 1
    cid = uuid.UUID(fx.clinic_id)
    async with database.session(clinic_id=cid) as s:
        await messaging.queue_message(
            s,
            clinic_id=cid,
            to_phone=chat.phone,
            phone_number_id="",
            category="reminder",
            key=f"test-reminder:{uuid.uuid4()}",
            run_at=rt.clock.now(),
            session={"type": "text", "text": "reminder"},
        )
        await s.commit()
    before = len(whatsapp.to(chat.phone))
    await jobs.drain(rt)
    assert len(whatsapp.to(chat.phone)) == before
    async with database.session(clinic_id=cid) as s:
        ob = await s.scalar(
            select(OutboxMessage).where(OutboxMessage.to_phone == chat.phone, OutboxMessage.category == "reminder")
        )
        assert (ob.status, ob.last_error) == ("skipped", "opted_out")
        p = await s.scalar(select(Patient).where(Patient.phone == chat.phone))
        assert p.opted_out_at is not None
        latest = (
            await s.scalars(
                select(ConsentEvent.granted)
                .where(ConsentEvent.patient_id == p.id, ConsentEvent.purpose == "reminders")
                .order_by(ConsentEvent.at.desc(), ConsentEvent.created_at.desc())
            )
        ).first()
        assert latest is False


async def test_inbox_reply_window_and_hand_back(client, rt, whatsapp, wa_clinic, clock, make_clinic):
    """FR-8.1/8.2/8.4, BR-9, AC-10 for inbox."""
    fx = await wa_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    await consent(chat)
    await chat.send("talk to staff")
    conv_id = (await client.get("/api/v1/inbox", headers=fx.h)).json()[0]["conversation_id"]
    msgs = (await client.get(f"/api/v1/inbox/conversations/{conv_id}/messages", headers=fx.h)).json()
    assert [m["direction"] for m in msgs][:2] == ["in", "out"]

    r = await client.post(
        f"/api/v1/inbox/conversations/{conv_id}/reply", json={"text": "Hello, how can we help?"}, headers=fx.h
    )
    assert r.status_code == 202
    await jobs.drain(rt)
    assert text_of(whatsapp.to(chat.phone)[-1]) == "Hello, how can we help?"

    other = await make_clinic(patients=0)
    assert (await client.get(f"/api/v1/inbox/conversations/{conv_id}/messages", headers=other.h)).status_code == 403

    assert (await client.post(f"/api/v1/inbox/conversations/{conv_id}/hand-back", headers=fx.h)).status_code == 204
    assert option_ids((await chat.send("hi"))[-1])[0] == "menu:book"  # assistant answers again

    clock.set(clock.now() + timedelta(hours=25))
    r = await client.post(f"/api/v1/inbox/conversations/{conv_id}/reply", json={"text": "late"}, headers=fx.h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "outside_24h_window"


async def test_dispatcher_quiet_hours_window_and_retry(client, rt, whatsapp, wa_clinic, clock, database):
    """BR-7 defer, BR-9 no template outside window → failed, transient errors retried and sent once."""
    fx = await wa_clinic()
    cid = uuid.UUID(fx.clinic_id)
    phone = rand_phone()
    clock.set(at(22, 0))
    async with database.session(clinic_id=cid) as s:
        p = Patient(clinic_id=cid, phone=phone, name="Q", age=30)
        s.add(p)
        await s.flush()
        s.add(
            ConsentEvent(
                clinic_id=cid,
                patient_id=p.id,
                purpose="reminders",
                granted=True,
                channel="dashboard",
                notice_version="t",
                at=clock.now(),
            )
        )
        await messaging.queue_message(
            s,
            clinic_id=cid,
            to_phone=phone,
            phone_number_id="",
            category="reminder",
            key=f"q:{uuid.uuid4()}",
            run_at=clock.now(),
            template={"name": "noshow_rebook", "language": "en", "params": ["X"]},
        )
        await messaging.queue_message(
            s,
            clinic_id=cid,
            to_phone=phone,
            phone_number_id="",
            category="transactional",
            key=f"w:{uuid.uuid4()}",
            run_at=clock.now(),
            session={"type": "text", "text": "no window"},
        )
        await s.commit()
    await jobs.drain(rt)
    assert whatsapp.to(phone) == []  # reminder deferred to 08:00; free text outside window failed
    async with database.session(clinic_id=cid) as s:
        rows = {o.category: o for o in (await s.scalars(select(OutboxMessage).where(OutboxMessage.to_phone == phone)))}
        assert rows["transactional"].status == "failed" and "outside_24h_window" in rows["transactional"].last_error
        assert rows["reminder"].status == "pending"

    clock.set(at(8, 0, day=1))
    whatsapp.fail_next.append(TransientSendError("http 503"))
    await jobs.drain(rt)
    assert whatsapp.to(phone) == []  # first attempt failed transiently → backoff
    clock.set(at(8, 5, day=1))
    await jobs.drain(rt)
    sent = whatsapp.to(phone)
    assert len(sent) == 1 and sent[0]["type"] == "template"

    # Delivery receipt via webhook updates the outbox (deduplicated like messages).
    async with database.session(clinic_id=cid) as s:
        pid = (
            await s.scalar(
                select(OutboxMessage).where(OutboxMessage.to_phone == phone, OutboxMessage.category == "reminder")
            )
        ).provider_message_id
    chat = Chat(client, rt, whatsapp, fx.pnid, phone)
    status_env = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": fx.pnid},
                            "statuses": [{"id": pid, "status": "delivered"}],
                        }
                    }
                ]
            }
        ]
    }
    assert await chat.post(status_env) == 200 and await chat.post(status_env) == 200
    await jobs.drain(rt)
    async with database.session(clinic_id=cid) as s:
        ob = await s.scalar(select(OutboxMessage).where(OutboxMessage.provider_message_id == pid))
        assert ob.delivery_status == "delivered"


async def test_noshow_rebook_message_and_attribution_source(client, rt, whatsapp, wa_clinic, clock):
    """FR-5.3, AC-6: no-show → rebook offer (consented) → one tap books with source noshow_rebook."""
    fx = await wa_clinic(patients=0)
    chat = Chat(client, rt, whatsapp, fx.pnid)
    out = await consent(chat, "appointment today")
    await chat.send(reply=[i for i in option_ids(out[-1]) if i.startswith("slot:")][0])
    await chat.send("Bhavna Joshi")
    await chat.send("29")
    await chat.send(reply="rem:yes")
    clock.set(at(13, 0))
    assert await noshow_sweep(rt) == 1
    await jobs.drain(rt)
    rebook = whatsapp.to(chat.phone)[-1]
    rebook_id = option_ids(rebook)[0]
    assert rebook_id.startswith("rebook:")
    days = await chat.send(reply=rebook_id)
    await chat.send(reply=[i for i in option_ids(days[-1]) if i.startswith("day:")][0])
    done = await chat.send(reply=[i for i in option_ids(whatsapp.to(chat.phone)[-1]) if i.startswith("slot:")][0])
    assert "✅" in text_of(done[0])
    upcoming = []
    for d in range(1, 8):
        day = (date(2026, 11, 23) + timedelta(days=d)).isoformat()
        upcoming += (await client.get("/api/v1/appointments", params={"day": day}, headers=fx.h)).json()
    assert [a["source"] for a in upcoming] == ["noshow_rebook"]


async def test_queue_alert_three_ahead_sent_once(client, rt, whatsapp, wa_clinic):
    """FR-4.3: each token alerted once when ≤ 3 ahead (template outside the 24 h window)."""
    fx = await wa_clinic()
    phones = [rand_phone() for _ in range(6)]
    tokens = []
    for p in phones:
        r = await client.post("/api/v1/queue/tokens", json={"doctor_id": fx.doctor_id, "phone": p}, headers=fx.h)
        tokens.append(r.json())
    sid = tokens[0]["queue_session_id"]
    await client.post(f"/api/v1/queue/sessions/{sid}/next", headers=fx.h)
    await jobs.drain(rt)
    alerted = [p for p in phones if whatsapp.to(p)]
    assert alerted == phones[1:5]  # tokens 2–5 are 0–3 ahead; token 6 is 4 ahead
    assert all(whatsapp.to(p)[0]["template"]["name"] == "token_alert" for p in alerted)
    await client.post(f"/api/v1/queue/sessions/{sid}/next", headers=fx.h)
    await jobs.drain(rt)
    assert [len(whatsapp.to(p)) for p in phones] == [0, 1, 1, 1, 1, 1]


async def test_token_and_status_by_whatsapp(client, rt, whatsapp, wa_clinic):
    """FR-4.1/4.2 by WhatsApp."""
    fx = await wa_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    await consent(chat)
    out = await chat.send("token")
    assert "*1*" in text_of(out[0]) and "/t/" in text_of(out[0])
    status = await chat.send("status")
    assert text_of(status[0]).startswith("Token 1") or "1" in text_of(status[0])


async def test_unclear_twice_hands_over(client, rt, whatsapp, wa_clinic):
    """FR-2.6: unclear request → menu, then staff."""
    fx = await wa_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    await consent(chat)
    first = await chat.send("qwerty")
    assert option_ids(first[-1])[0] == "menu:book"
    await chat.send("zxcvb")
    assert [i["reason"] for i in (await client.get("/api/v1/inbox", headers=fx.h)).json()] == ["unclear"]


async def test_handover_ticket_unique_per_conversation(client, rt, whatsapp, wa_clinic, database):
    fx = await wa_clinic()
    chat = Chat(client, rt, whatsapp, fx.pnid)
    await chat.send("chest pain")
    await chat.send("still chest pain")
    async with database.session(clinic_id=uuid.UUID(fx.clinic_id)) as s:
        n = len((await s.scalars(select(HandoverTicket).where(HandoverTicket.status == "open"))).all())
    assert n == 1
