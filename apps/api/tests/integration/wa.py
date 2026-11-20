"""WhatsApp test helpers: a patient's phone driving the real webhook → jobs → dispatcher path."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
from tests.conftest import WA_SECRET, rand_phone

from clinicdesk.integrations.whatsapp import option_ids
from clinicdesk.modules.jobs import service as jobs


class Chat:
    """A patient's WhatsApp, driving the real webhook → jobs → dispatcher path."""

    def __init__(self, client, rt, whatsapp, pnid: str, phone: str | None = None):
        self.client, self.rt, self.wa, self.pnid = client, rt, whatsapp, pnid
        self.phone = phone or rand_phone()

    async def post(self, body: dict, *, sign: bool = True) -> int:
        raw = json.dumps(body).encode()
        sig = "sha256=" + hmac.new(WA_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        r = await self.client.post(
            "/api/v1/webhooks/whatsapp",
            content=raw,
            headers={"x-hub-signature-256": sig if sign else "sha256=bad", "content-type": "application/json"},
        )
        return r.status_code

    def envelope(self, msg: dict) -> dict:
        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": self.pnid},
                                "contacts": [{"wa_id": self.phone.lstrip("+")}],
                                "messages": [msg],
                            },
                        }
                    ],
                }
            ],
        }

    def msg(self, text: str | None = None, reply: str | None = None, mid: str | None = None) -> dict:
        base = {"from": self.phone.lstrip("+"), "id": mid or f"wamid.in.{uuid.uuid4().hex}", "timestamp": "0"}
        if reply is not None:
            return base | {
                "type": "interactive",
                "interactive": {"type": "list_reply", "list_reply": {"id": reply, "title": reply}},
            }
        return base | {"type": "text", "text": {"body": text}}

    async def button(self, payload: str, title: str = "button") -> list[dict]:
        """Quick-reply tap on a *template* message (arrives as type "button")."""
        before = len(self.wa.to(self.phone))
        msg = {
            "from": self.phone.lstrip("+"),
            "id": f"wamid.in.{uuid.uuid4().hex}",
            "timestamp": "0",
            "type": "button",
            "button": {"payload": payload, "text": title},
        }
        assert await self.post(self.envelope(msg)) == 200
        await jobs.drain(self.rt)
        return self.wa.to(self.phone)[before:]

    async def send(self, text: str | None = None, reply: str | None = None) -> list[dict]:
        before = len(self.wa.to(self.phone))
        assert await self.post(self.envelope(self.msg(text, reply))) == 200
        await jobs.drain(self.rt)
        return self.wa.to(self.phone)[before:]


@pytest.fixture
def wa_clinic(client, make_clinic):
    async def _make(patients: int = 0, phone: str | None = None):
        fx = await make_clinic(patients=patients)
        pnid = str(uuid.uuid4().int)[:15]
        body = {
            "wa_phone_number_id": pnid,
            "phone": phone or rand_phone(),
            "address": "CG Road, Ahmedabad",
            "map_url": "https://maps.example/x",
        }
        r = await client.patch("/api/v1/clinic", json=body, headers=fx.h)
        assert r.status_code == 200, r.text
        fx.pnid, fx.phone = pnid, r.json()["phone"]
        return fx

    return _make


async def consent(chat: Chat, first: str = "Hi") -> list[dict]:
    out = await chat.send(first)
    assert option_ids(out[-1]) == ["consent:yes", "consent:no"]
    return await chat.send(reply="consent:yes")
