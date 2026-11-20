"""Authenticated WebSocket for live dashboard signals (NFR-2).

Protocol: client connects to /api/v1/ws, then sends {"type": "auth", "token": "<access token>"} within
5 seconds (tokens never go in the URL, where they would be logged). The server then forwards the
clinic's signals, e.g. {"type": "queue.updated", "queue_session_id": ...}. Clients refetch over REST.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from clinicdesk.core.events import clinic_channel
from clinicdesk.core.security import decode_access_token

router = APIRouter()
AUTH_TIMEOUT_S = 5


@router.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await websocket.accept()
    app = websocket.app
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_S)
        msg = json.loads(raw)
        claims = decode_access_token(
            str(msg.get("token", "")), secret=app.state.settings.jwt_secret, now=app.state.clock.now()
        )
    except (TimeoutError, ValueError, jwt.InvalidTokenError, WebSocketDisconnect):
        with contextlib.suppress(Exception):
            await websocket.close(code=4401)
        return
    if claims.clinic_id is None or getattr(app.state, "broker", None) is None:
        await websocket.close(code=4403 if claims.clinic_id is None else 1011)
        return
    await websocket.send_text(json.dumps({"type": "ready"}))
    async with app.state.broker.subscribe(clinic_channel(claims.clinic_id)) as stream:
        forward = asyncio.create_task(_forward(websocket, stream))
        try:
            while True:  # keep reading so disconnects are noticed
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            forward.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await forward


async def _forward(websocket: WebSocket, stream) -> None:  # type: ignore[no-untyped-def]
    async for message in stream:
        await websocket.send_text(message)
