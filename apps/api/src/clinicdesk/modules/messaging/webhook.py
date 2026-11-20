"""WhatsApp Cloud API webhook (NFR-4): verify → persist → enqueue → 200. No processing in the request."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.dialects.postgresql import insert

from clinicdesk.core.errors import Forbidden, Unauthorized
from clinicdesk.core.logging import log
from clinicdesk.integrations.whatsapp import verify_signature
from clinicdesk.modules.jobs import service as jobs
from clinicdesk.modules.messaging.models import InboundEvent

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
MAX_BODY = 1_000_000


@router.get("/whatsapp", response_class=PlainTextResponse)
async def verify(
    request: Request,
    mode: Annotated[str, Query(alias="hub.mode")] = "",
    token: Annotated[str, Query(alias="hub.verify_token")] = "",
    challenge: Annotated[str, Query(alias="hub.challenge")] = "",
) -> str:
    expected = request.app.state.settings.whatsapp_verify_token
    if mode != "subscribe" or not expected or token != expected:
        raise Forbidden("verification failed")
    return challenge


def _items(body: dict[str, Any]) -> list[tuple[str, str, str | None, dict[str, Any]]]:
    """(external_id, kind, phone_number_id, payload) for every message / status in the delivery."""
    out = []
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            pnid = value.get("metadata", {}).get("phone_number_id")
            for msg in value.get("messages", []):
                out.append((str(msg["id"]), "message", pnid, {"message": msg, "contacts": value.get("contacts", [])}))
            for st in value.get("statuses", []):
                out.append((f"status:{st['id']}:{st['status']}", "status", pnid, {"status": st}))
    return out


@router.post("/whatsapp")
async def receive(request: Request) -> Response:
    rt = request.app.state.runtime
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise Unauthorized("payload too large", code="payload_too_large")
    if not verify_signature(raw, request.headers.get("x-hub-signature-256"), rt.settings.whatsapp_app_secret):
        log.warning("whatsapp_bad_signature")
        raise Unauthorized("bad signature", code="bad_signature")
    try:
        body = json.loads(raw)
    except ValueError:
        return Response(status_code=200)  # signed but malformed: acknowledge, nothing to do
    now = rt.clock.now()
    async with rt.db.session(bypass_rls=True) as s:  # platform path: clinic unknown until processed
        for external_id, kind, pnid, payload in _items(body):
            event_id = await s.scalar(
                insert(InboundEvent)
                .values(
                    provider="whatsapp", external_id=external_id[:160], kind=kind, phone_number_id=pnid, payload=payload
                )
                .on_conflict_do_nothing(index_elements=["provider", "external_id"])
                .returning(InboundEvent.id)
            )
            if event_id is not None:  # duplicates from Meta's at-least-once delivery are dropped here
                await jobs.enqueue(
                    s,
                    clinic_id=None,
                    kind="wa.inbound",
                    run_at=now,
                    dedup_key=f"wa.inbound:{event_id}",
                    payload={"event_id": str(event_id)},
                )
        await s.commit()
        await jobs.flush_wakes(s, rt.waker)
    return Response(status_code=200)
