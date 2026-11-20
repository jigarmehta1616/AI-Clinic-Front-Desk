"""Enqueue, claim and execute scheduled jobs (ADR-0004).

* `enqueue` joins the caller's business transaction; `dedup_key` makes it idempotent. After that
  transaction commits, `flush_wakes` asks the worker to run the job immediately (NFR-1); the
  1-minute tick is the safety net if the wake-up is lost.
* `claim_due` / `claim_one` atomically mark jobs `running` with `FOR UPDATE SKIP LOCKED`, so
  concurrent workers never execute the same job. Stale `running` jobs (worker died) are reclaimed.
* Handlers must be idempotent and re-check preconditions. They may raise `Reschedule` to defer
  without counting a failed attempt (e.g. quiet hours).
"""

from __future__ import annotations

import traceback
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import event, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from clinicdesk.core import events
from clinicdesk.core.logging import log
from clinicdesk.core.runtime import Runtime, Waker
from clinicdesk.modules.jobs import policy
from clinicdesk.modules.jobs.models import ScheduledJob


@dataclass
class JobContext:
    s: AsyncSession  # tenant-scoped (or bypass for platform jobs)
    rt: Runtime
    job: ScheduledJob


class Reschedule(Exception):
    def __init__(self, run_at: datetime, reason: str) -> None:
        super().__init__(reason)
        self.run_at = run_at
        self.reason = reason


Handler = Callable[[JobContext], Awaitable[None]]
HANDLERS: dict[str, Handler] = {}

_PENDING_WAKE = "pending_wake"
_COMMITTED_WAKE = "committed_wake"


def handler(kind: str) -> Callable[[Handler], Handler]:
    def _register(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return _register


@event.listens_for(Session, "after_commit")
def _wake_after_commit(session: Session) -> None:
    pending = session.info.pop(_PENDING_WAKE, None)
    if pending:
        session.info.setdefault(_COMMITTED_WAKE, []).extend(pending)


@event.listens_for(Session, "after_soft_rollback")
def _drop_wakes(session: Session, _prev: Any) -> None:
    session.info.pop(_PENDING_WAKE, None)


async def flush_wakes(s: AsyncSession, waker: Waker | None) -> None:
    jobs = s.info.pop(_COMMITTED_WAKE, None)
    if jobs and waker is not None:
        await waker.wake(jobs)


async def flush_after_commit(s: AsyncSession, rt: Runtime) -> None:
    """Publish live-update signals and wake jobs created by the committed transaction(s)."""
    await events.flush(s, rt.broker)
    await flush_wakes(s, rt.waker)


async def enqueue(
    s: AsyncSession,
    *,
    clinic_id: uuid.UUID | None,
    kind: str,
    run_at: datetime,
    dedup_key: str,
    payload: dict[str, Any] | None = None,
) -> uuid.UUID | None:
    """Returns the new job id, or None if a job with this dedup_key already exists (no-op)."""
    result = await s.execute(
        insert(ScheduledJob)
        .values(clinic_id=clinic_id, kind=kind, run_at=run_at, dedup_key=dedup_key, payload=payload or {})
        .on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(ScheduledJob.id)
    )
    job_id = result.scalar_one_or_none()
    if job_id is not None:
        s.info.setdefault(_PENDING_WAKE, []).append((job_id, run_at))
    return job_id


async def cancel(s: AsyncSession, dedup_key: str) -> None:
    await s.execute(
        update(ScheduledJob)
        .where(ScheduledJob.dedup_key == dedup_key, ScheduledJob.status == "pending")
        .values(status="cancelled")
    )


def _claim_stmt(now: datetime, limit: int, job_id: uuid.UUID | None = None) -> Any:
    due = (
        select(ScheduledJob.id)
        .where(
            or_(
                (ScheduledJob.status == "pending") & (ScheduledJob.run_at <= now),
                (ScheduledJob.status == "running") & (ScheduledJob.locked_at < now - policy.STALE_LOCK),
            )
        )
        .order_by(ScheduledJob.run_at, ScheduledJob.seq)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    if job_id is not None:
        due = due.where(ScheduledJob.id == job_id)
    return (
        update(ScheduledJob)
        .where(ScheduledJob.id.in_(due.scalar_subquery()))
        .values(status="running", locked_at=now, attempts=ScheduledJob.attempts + 1)
        .returning(ScheduledJob)
    )


async def claim_due(rt: Runtime, limit: int = 50, job_id: uuid.UUID | None = None) -> list[ScheduledJob]:
    async with rt.db.session(bypass_rls=True) as s:  # platform worker path: spans tenants
        jobs = list((await s.scalars(_claim_stmt(rt.clock.now(), limit, job_id))).all())
        await s.commit()
        # UPDATE ... RETURNING has no guaranteed order; execute in schedule order (reply ordering depends on it).
        return sorted(jobs, key=lambda j: (j.run_at, j.seq))


async def _finish(rt: Runtime, job_id: uuid.UUID, **values: Any) -> None:
    async with rt.db.session(bypass_rls=True) as s:
        await s.execute(update(ScheduledJob).where(ScheduledJob.id == job_id).values(**values))
        await s.commit()


async def execute(rt: Runtime, job: ScheduledJob) -> str:
    fn = HANDLERS.get(job.kind)
    if fn is None:
        await _finish(rt, job.id, status="failed", last_error=f"no handler for {job.kind}", finished_at=rt.clock.now())
        log.error("job_no_handler", kind=job.kind, job_id=str(job.id))
        return "failed"
    try:
        async with rt.db.session(clinic_id=job.clinic_id, bypass_rls=job.clinic_id is None) as s:
            await fn(JobContext(s, rt, job))
            await s.commit()
            await flush_after_commit(s, rt)
    except Reschedule as r:
        await _finish(
            rt,
            job.id,
            status="pending",
            run_at=r.run_at,
            attempts=max(job.attempts - 1, 0),
            locked_at=None,
            last_error=f"deferred: {r.reason}",
        )
        await (rt.waker.wake([(job.id, r.run_at)]) if rt.waker else _noop())
        return "deferred"
    except Exception as e:
        now = rt.clock.now()
        give_up = policy.should_give_up(job.attempts, job.max_attempts)
        retry_at = job.run_at if give_up else policy.next_attempt(now, job.attempts)
        await _finish(
            rt,
            job.id,
            status="failed" if give_up else "pending",
            run_at=retry_at,
            last_error="".join(traceback.format_exception_only(e))[-2000:],
            finished_at=now if give_up else None,
            locked_at=None,
        )
        log.warning("job_failed", kind=job.kind, job_id=str(job.id), attempts=job.attempts, give_up=give_up)
        if not give_up and rt.waker:
            await rt.waker.wake([(job.id, retry_at)])
        return "failed" if give_up else "retry"
    await _finish(rt, job.id, status="done", finished_at=rt.clock.now(), locked_at=None, last_error=None)
    return "done"


async def _noop() -> None:
    return None


async def run_due(rt: Runtime, limit: int = 50) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in await claim_due(rt, limit):
        outcome = await execute(rt, job)
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


async def run_one(rt: Runtime, job_id: uuid.UUID) -> str | None:
    """Fast path used by the worker's `run_job` (woken right after the enqueueing commit)."""
    jobs = await claim_due(rt, 1, job_id)
    return await execute(rt, jobs[0]) if jobs else None


async def drain(rt: Runtime, max_rounds: int = 10) -> dict[str, int]:
    """Run due jobs until none are left (tests and one-off scripts)."""
    total: dict[str, int] = {}
    for _ in range(max_rounds):
        counts = await run_due(rt)
        if not counts:
            break
        for k, v in counts.items():
            total[k] = total.get(k, 0) + v
    return total
