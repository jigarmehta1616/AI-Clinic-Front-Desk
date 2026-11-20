"""End-to-end smoke test against a running dev server (real Postgres, Redis, WebSocket).

Usage (dev only — reads the console OTP from the server's log file):
    python scripts/smoke_e2e.py http://127.0.0.1:8000 path/to/server.log
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import uuid
from pathlib import Path

import httpx
import websockets

BASE, LOG = sys.argv[1], Path(sys.argv[2])


def otp_from_log() -> str:
    codes = re.findall(r'"code":\s*"(\d{6})"', LOG.read_text(encoding="utf8", errors="ignore"))
    if not codes:
        raise SystemExit("no dev OTP found in server log")
    return codes[-1]


async def main() -> None:
    phone = "+919" + str(uuid.uuid4().int)[:9]
    async with httpx.AsyncClient(base_url=f"{BASE}/api/v1", timeout=10) as c:
        assert (await c.get("/health")).json() == {"status": "ok"}
        assert (await c.post("/auth/otp/request", json={"phone": phone})).status_code == 202
        await asyncio.sleep(0.3)
        tok = (await c.post("/auth/otp/verify", json={"phone": phone, "code": otp_from_log()})).json()
        h = {"Authorization": f"Bearer {tok['access_token']}"}
        r = await c.post(
            "/clinics",
            json={"name": "Smoke Clinic", "slug": "S" + uuid.uuid4().hex[:8].upper(), "specialty": "dental"},
            headers=h,
        )
        assert r.status_code == 201, r.text
        h = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
        doctor = (await c.post("/doctors", json={"name": "Dr. Smoke"}, headers=h)).json()
        sessions = [{"weekday": d, "start_time": "00:00", "end_time": "23:59", "max_tokens": 50} for d in range(7)]
        assert (await c.put(f"/doctors/{doctor['id']}/sessions", json={"sessions": sessions}, headers=h)).status_code == 200

        ws_url = BASE.replace("http", "ws") + "/api/v1/ws"
        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps({"type": "auth", "token": h["Authorization"][7:]}))
            assert json.loads(await asyncio.wait_for(ws.recv(), 3))["type"] == "ready"
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            entry = (await c.post("/queue/tokens", json={"doctor_id": doctor["id"]}, headers=h)).json()
            msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
            latency_ms = (loop.time() - t0) * 1000
            assert msg["type"] == "queue.updated" and msg["queue_session_id"] == entry["queue_session_id"]

        pub = (await c.get(f"/public/queue/{entry['public_code']}")).json()
        assert pub["token_no"] == entry["token_no"] and "phone" not in pub
        nxt = (await c.post(f"/queue/sessions/{entry['queue_session_id']}/next", headers=h)).json()
        assert nxt["id"] == entry["id"]

        async with websockets.connect(ws_url) as ws:  # bad token is rejected
            await ws.send(json.dumps({"type": "auth", "token": "nope"}))
            try:
                await asyncio.wait_for(ws.recv(), 3)
                raise AssertionError("unauthenticated socket received data")
            except websockets.ConnectionClosed as e:
                assert e.rcvd is not None and e.rcvd.code == 4401

    print(f"SMOKE OK — token {entry['token_no']}, WS signal round-trip {latency_ms:.0f} ms")


asyncio.run(main())
