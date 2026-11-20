"""WhatsApp Business Cloud API adapter (Meta Graph API).

* `verify_signature` — X-Hub-Signature-256 HMAC over the raw request body.
* `build_payload` — our neutral message shapes → Graph API JSON (text, reply buttons, list, template).
* `CloudApiClient` — real sender. Not exercised against Meta until credentials exist (see project-status).
* `FakeWhatsAppClient` — tests; `LoggingWhatsAppClient` — local dev without credentials (refused in production).

Neutral shapes (stored in `outbox_messages.session_payload` / `.template`):
  {"type": "text", "text": "..."}
  {"type": "buttons", "text": "...", "buttons": [{"id": "...", "title": "..."}]}           # ≤ 3 buttons
  {"type": "list", "text": "...", "button": "...", "rows": [{"id", "title", "description"?}]}  # ≤ 10 rows
  template: {"name": "...", "language": "gu|hi|en", "params": ["..."]}
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from clinicdesk.core.logging import log, mask_phone

LIMITS = {"button_title": 20, "row_title": 24, "row_description": 72, "list_button": 20, "body": 1024, "text": 4096}
LANG_CODES = {"en": "en", "hi": "hi", "gu": "gu"}


class SendError(Exception):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class TransientSendError(SendError):
    """Retry later (rate limit, 5xx, network)."""


class PermanentSendError(SendError):
    """Do not retry (policy/validation error, e.g. outside the 24 h window, invalid number)."""


def verify_signature(raw_body: bytes, header: str | None, app_secret: str) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:])


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_payload(to: str, session: dict[str, Any] | None, template: dict[str, Any] | None) -> dict[str, Any]:
    base: dict[str, Any] = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to.lstrip("+")}
    if template is not None:
        components = []
        if template.get("params"):
            components.append(
                {"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in template["params"]]}
            )
        for i, btn in enumerate(template.get("quick_replies", [])):
            components.append(
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": str(i),
                    "parameters": [{"type": "payload", "payload": btn}],
                }
            )
        return base | {
            "type": "template",
            "template": {
                "name": template["name"],
                "language": {"code": LANG_CODES.get(template["language"], "en")},
                "components": components,
            },
        }
    assert session is not None
    kind = session["type"]
    if kind == "text":
        return base | {"type": "text", "text": {"preview_url": True, "body": _clip(session["text"], LIMITS["text"])}}
    if kind == "buttons":
        return base | {
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": _clip(session["text"], LIMITS["body"])},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": b["id"], "title": _clip(b["title"], LIMITS["button_title"])}}
                        for b in session["buttons"][:3]
                    ]
                },
            },
        }
    if kind == "list":
        rows = []
        for r in session["rows"][:10]:
            row = {"id": r["id"], "title": _clip(r["title"], LIMITS["row_title"])}
            if r.get("description"):
                row["description"] = _clip(r["description"], LIMITS["row_description"])
            rows.append(row)
        return base | {
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": _clip(session["text"], LIMITS["body"])},
                "action": {
                    "button": _clip(session["button"], LIMITS["list_button"]),
                    "sections": [{"title": _clip(session.get("section", "Options"), 24), "rows": rows}],
                },
            },
        }
    raise ValueError(f"unknown session payload type {kind}")


class WhatsAppClient(Protocol):
    async def send(self, phone_number_id: str, payload: dict[str, Any]) -> str:
        """Returns the provider message id. Raises TransientSendError / PermanentSendError."""
        ...


class CloudApiClient:
    def __init__(self, access_token: str, api_version: str = "v21.0", timeout_s: float = 10.0) -> None:
        self._http = httpx.AsyncClient(
            base_url=f"https://graph.facebook.com/{api_version}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout_s,
        )

    async def send(self, phone_number_id: str, payload: dict[str, Any]) -> str:
        try:
            r = await self._http.post(f"/{phone_number_id}/messages", json=payload)
        except httpx.TransportError as e:
            raise TransientSendError(f"network: {type(e).__name__}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise TransientSendError(f"http {r.status_code}", code=str(r.status_code))
        body = r.json() if r.content else {}
        if r.status_code >= 400:
            err = body.get("error", {})
            raise PermanentSendError(
                str(err.get("message", "rejected"))[:300], code=str(err.get("code", r.status_code))
            )
        return str(body["messages"][0]["id"])

    async def close(self) -> None:
        await self._http.aclose()


@dataclass
class FakeWhatsAppClient:
    """Test double. `fail_next` lets tests inject provider errors."""

    sent: list[dict[str, Any]] = field(default_factory=list)
    fail_next: list[SendError] = field(default_factory=list)

    async def send(self, phone_number_id: str, payload: dict[str, Any]) -> str:
        if self.fail_next:
            raise self.fail_next.pop(0)
        self.sent.append({"from": phone_number_id, **payload})
        return f"wamid.fake.{uuid.uuid4().hex}"  # globally unique, like Meta's ids

    def to(self, phone: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["to"] == phone.lstrip("+")]


class LoggingWhatsAppClient:
    """Local development without Meta credentials: logs instead of sending."""

    def __init__(self) -> None:
        self._n = 0

    async def send(self, phone_number_id: str, payload: dict[str, Any]) -> str:
        self._n += 1
        log.info("dev_whatsapp_send", to=mask_phone(payload["to"]), type=payload["type"])
        return f"wamid.dev.{uuid.uuid4().hex}"  # unique across worker restarts


def text_of(payload: dict[str, Any]) -> str:
    """Human-readable body of a Graph payload (tests, logs, inbox)."""
    if payload["type"] == "text":
        return str(payload["text"]["body"])
    if payload["type"] == "interactive":
        return str(payload["interactive"]["body"]["text"])
    return f"[template {payload['template']['name']}]"


def option_ids(payload: dict[str, Any]) -> list[str]:
    if payload["type"] != "interactive":
        return []
    action = payload["interactive"]["action"]
    if "buttons" in action:
        return [b["reply"]["id"] for b in action["buttons"]]
    return [r["id"] for s in action["sections"] for r in s["rows"]]
