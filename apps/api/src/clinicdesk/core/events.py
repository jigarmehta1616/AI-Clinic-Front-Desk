"""Live-update signals (NFR-2).

Services call `emit(session, channel, event)`; events are buffered on the session and only become
publishable after the transaction commits (rolled-back work never reaches dashboards). The request
dependency / worker then calls `flush(session, broker)`.

Events are *signals* ("queue changed"), never data: clients refetch the snapshot over the
authenticated API, so a dropped or duplicated signal is harmless.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from sqlalchemy import event
from sqlalchemy.orm import Session

from clinicdesk.core.logging import log

_PENDING = "pending_events"
_COMMITTED = "committed_events"


def clinic_channel(clinic_id: Any) -> str:
    return f"clinic:{clinic_id}"


def emit(session: Any, channel: str, payload: dict[str, Any]) -> None:
    """`session` may be an AsyncSession or a sync Session."""
    info = session.info
    info.setdefault(_PENDING, []).append((channel, payload))


@event.listens_for(Session, "after_commit")
def _move_to_committed(session: Session) -> None:
    pending = session.info.pop(_PENDING, None)
    if pending:
        session.info.setdefault(_COMMITTED, []).extend(pending)


@event.listens_for(Session, "after_soft_rollback")
def _drop_pending(session: Session, _previous_transaction: Any) -> None:
    session.info.pop(_PENDING, None)


class Broker(Protocol):
    async def publish(self, channel: str, message: str) -> None: ...

    def subscribe(self, channel: str) -> Any: ...  # async context manager yielding AsyncIterator[str]


async def flush(session: Any, broker: Broker | None) -> None:
    events = session.info.pop(_COMMITTED, None)
    if not events or broker is None:
        return
    for channel, payload in events:
        try:
            await broker.publish(channel, json.dumps(payload, default=str))
        except Exception as e:  # signals are best-effort; data is already committed
            log.warning("event_publish_failed", channel=channel, error=type(e).__name__)


class MemoryBroker:
    """In-process broker for tests and single-process dev."""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[str]]] = defaultdict(set)
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> None:
        self.published.append((channel, message))
        for q in list(self._subs[channel]):
            q.put_nowait(message)

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[AsyncIterator[str]]:
        q: asyncio.Queue[str] = asyncio.Queue()
        self._subs[channel].add(q)

        async def _iter() -> AsyncIterator[str]:
            while True:
                yield await q.get()

        try:
            yield _iter()
        finally:
            self._subs[channel].discard(q)


class RedisBroker:
    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(url, decode_responses=True)

    async def publish(self, channel: str, message: str) -> None:
        await self._redis.publish(channel, message)

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[AsyncIterator[str]]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)

        async def _iter() -> AsyncIterator[str]:
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    yield str(msg["data"])

        try:
            yield _iter()
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    async def close(self) -> None:
        await self._redis.aclose()
