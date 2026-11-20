"""Real-process smoke test of the WhatsApp path: signed webhook → API → Redis wake-up → ARQ worker →
assistant turn → outbox → dispatcher (dev 'log' provider, nothing reaches Meta).

Usage (dev only):
    python scripts/smoke_whatsapp.py http://127.0.0.1:8000 path/to/server.log
Requires WHATSAPP_APP_SECRET in .env and a running worker (`arq clinicdesk.worker.WorkerSettings`).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import sys
import time
import uuid
from pathlib import Path

import asyncpg
import httpx

BASE, LOG = sys.argv[1], Path(sys.argv[2])
ENV = dict(
    line.split("=", 1) for line in Path(".env").read_text(encoding="utf8").splitlines() if "=" in line and line[0] != "#"
)
SECRET = ENV["WHATSAPP_APP_SECRET"].split("#")[0].strip()
OWNER_DSN = ENV["MIGRATION_DATABASE_URL"].split("#")[0].strip().replace("postgresql+psycopg://", "postgresql://")


def otp_from_log() -> str:
    return re.findall(r'"code":\s*"(\d{6})"', LOG.read_text(encoding="utf8", errors="ignore"))[-1]


async def main() -> None:
    owner = "+919" + str(uuid.uuid4().int)[:9]
    patient = "919" + str(uuid.uuid4().int)[:9]
    pnid = str(uuid.uuid4().int)[:15]
    async with httpx.AsyncClient(base_url=f"{BASE}/api/v1", timeout=10) as c:
        await c.post("/auth/otp/request", json={"phone": owner})
        await asyncio.sleep(0.3)
        tok = (await c.post("/auth/otp/verify", json={"phone": owner, "code": otp_from_log()})).json()
        h = {"Authorization": f"Bearer {tok['access_token']}"}
        r = await c.post("/clinics", json={"name": "Smoke WA", "slug": "W" + uuid.uuid4().hex[:8].upper(),
                                           "specialty": "physio"}, headers=h)
        h = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
        assert (await c.patch("/clinic", json={"wa_phone_number_id": pnid}, headers=h)).status_code == 200

        body = json.dumps({"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": pnid}, "messages": [
            {"from": patient, "id": f"wamid.smoke.{uuid.uuid4().hex}", "type": "text", "text": {"body": "Hi"}}]}}]}]})
        sig = "sha256=" + hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        t0 = time.perf_counter()
        r = await c.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sig,
                                                                       "content-type": "application/json"})
        ack_ms = (time.perf_counter() - t0) * 1000
        assert r.status_code == 200, r.text

    conn = await asyncpg.connect(OWNER_DSN)
    try:
        for _ in range(100):
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.bypass_rls', 'on', true)")
                row = await conn.fetchrow(
                    "SELECT status, sent_at, created_at FROM outbox_messages WHERE to_phone = $1", "+" + patient
                )
            if row and row["status"] == "sent":
                break
            await asyncio.sleep(0.05)
        else:
            raise SystemExit(f"reply not sent in 5 s (last outbox row: {row})")
    finally:
        await conn.close()
    total_ms = (time.perf_counter() - t0) * 1000
    print(f"WHATSAPP SMOKE OK — webhook ack {ack_ms:.0f} ms, reply dispatched {total_ms:.0f} ms after webhook")


asyncio.run(main())
