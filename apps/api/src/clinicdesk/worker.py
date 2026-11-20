"""ARQ worker entrypoint: `arq clinicdesk.worker.WorkerSettings`.

ARQ provides wake-ups (`run_job`, enqueued right after a job is committed) and clock ticks; all work
state is in PostgreSQL (ADR-0004), so a Redis restart delays work by at most one tick and loses nothing.
"""

from __future__ import annotations

import uuid
from typing import Any

from arq import cron
from arq.connections import RedisSettings

import clinicdesk.handlers  # noqa: F401  registers job handlers
from clinicdesk.core.clock import SystemClock
from clinicdesk.core.config import get_settings
from clinicdesk.core.db import Database
from clinicdesk.core.events import RedisBroker
from clinicdesk.core.logging import configure_logging, log
from clinicdesk.core.runtime import ArqWaker, Runtime
from clinicdesk.main import whatsapp_client
from clinicdesk.modules.booking.sweeps import noshow_sweep
from clinicdesk.modules.jobs import service as jobs


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    settings = get_settings()
    clock = SystemClock()
    ctx["rt"] = Runtime(
        settings=settings,
        db=Database(settings.database_url, pool_size=5),
        clock=clock,
        whatsapp=whatsapp_client(settings),
        waker=ArqWaker(ctx["redis"], clock),
        broker=RedisBroker(settings.redis_url),
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    rt: Runtime = ctx["rt"]
    await rt.db.dispose()
    await rt.broker.close()
    if hasattr(rt.whatsapp, "close"):
        await rt.whatsapp.close()


async def run_job(ctx: dict[str, Any], job_id: str) -> str | None:
    return await jobs.run_one(ctx["rt"], uuid.UUID(job_id))


async def scheduler_tick(ctx: dict[str, Any]) -> dict[str, int]:
    counts = await jobs.run_due(ctx["rt"])
    if counts:
        log.info("scheduler_tick", **counts)
    return counts


async def noshow_tick(ctx: dict[str, Any]) -> int:
    marked = await noshow_sweep(ctx["rt"])
    if marked:
        log.info("noshow_sweep", marked=marked)
    return marked


class WorkerSettings:
    functions = [run_job]
    cron_jobs = [
        cron(scheduler_tick, second=0, unique=True, run_at_startup=True),  # every minute (NFR-5)
        cron(noshow_tick, minute=set(range(0, 60, 5)), second=30, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 20
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
