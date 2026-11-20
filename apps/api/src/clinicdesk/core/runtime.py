"""Process-wide dependencies shared by the API and the worker (one object, injected everywhere).

Keeping provider clients here (not imported globals) is what lets tests swap in fakes and lets
production refuse them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from clinicdesk.core.clock import Clock
from clinicdesk.core.config import Settings
from clinicdesk.core.db import Database
from clinicdesk.core.logging import log


class Waker(Protocol):
    """Asks the worker to run specific jobs now (or at `run_at`) instead of waiting for the next tick."""

    async def wake(self, jobs: list[tuple[uuid.UUID, datetime]]) -> None: ...


class ArqWaker:
    def __init__(self, pool: Any, clock: Clock) -> None:
        self._pool = pool
        self._clock = clock

    async def wake(self, jobs: list[tuple[uuid.UUID, datetime]]) -> None:
        now = self._clock.now()
        for job_id, run_at in jobs:
            try:
                await self._pool.enqueue_job(
                    "run_job", str(job_id), _job_id=f"run:{job_id}", _defer_until=run_at if run_at > now else None
                )
            except Exception as e:  # the 1-minute tick is the safety net
                log.warning("wake_failed", job_id=str(job_id), error=type(e).__name__)


class LazyArqWaker:
    """Connects to Redis on first use and reconnects after failures, so an API started while Redis was down
    recovers instant wake-ups by itself (until then the 1-minute tick delivers the work)."""

    RETRY_AFTER_S = 10.0

    def __init__(self, redis_url: str, clock: Clock) -> None:
        self._url = redis_url
        self._clock = clock
        self._pool: Any = None
        self._next_try = 0.0

    async def _waker(self) -> ArqWaker | None:
        import time

        if self._pool is None and time.monotonic() >= self._next_try:
            try:
                from arq import create_pool
                from arq.connections import RedisSettings

                settings = RedisSettings.from_dsn(self._url)
                settings.conn_retries = 0
                self._pool = await create_pool(settings)
            except Exception as e:
                self._next_try = time.monotonic() + self.RETRY_AFTER_S
                log.warning("arq_unavailable", error=type(e).__name__)
        return ArqWaker(self._pool, self._clock) if self._pool is not None else None

    async def wake(self, jobs: list[tuple[uuid.UUID, datetime]]) -> None:
        waker = await self._waker()
        if waker is not None:
            await waker.wake(jobs)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()


class RecordingWaker:
    def __init__(self) -> None:
        self.woken: list[uuid.UUID] = []

    async def wake(self, jobs: list[tuple[uuid.UUID, datetime]]) -> None:
        self.woken.extend(j for j, _ in jobs)


@dataclass
class Runtime:
    settings: Settings
    db: Database
    clock: Clock
    whatsapp: Any  # integrations.whatsapp.WhatsAppClient
    waker: Waker | None = None
    broker: Any = None  # core.events.Broker
