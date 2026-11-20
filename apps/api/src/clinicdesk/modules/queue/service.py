"""Live token queue (FR-4.1..4.7, BR-5, BR-6).

Every mutation locks the `queue_sessions` row first, so token numbers, the BR-5 limit and the
"current patient" pointer are serialised per doctor session. Ordering is the pure function in
`ordering.py`; this module only loads state, applies it and persists the result.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core import events
from clinicdesk.core.clock import Clock
from clinicdesk.core.context import RequestContext
from clinicdesk.core.db import Database, commit
from clinicdesk.core.errors import Forbidden, PolicyViolation
from clinicdesk.modules.audit import service as audit
from clinicdesk.modules.patients import service as patients
from clinicdesk.modules.queue import ordering
from clinicdesk.modules.queue import policy as qpolicy
from clinicdesk.modules.queue.models import QueueEntry, QueueSession
from clinicdesk.modules.scheduling import service as scheduling
from clinicdesk.modules.scheduling.models import DoctorSession, ScheduleException
from clinicdesk.modules.tenancy.models import Clinic
from clinicdesk.modules.tenancy.schemas import ClinicSettings


@dataclass(frozen=True, slots=True)
class EntryView:
    entry: QueueEntry
    ahead: int | None
    eta: datetime | None


@dataclass(frozen=True, slots=True)
class Snapshot:
    session: QueueSession
    current: QueueEntry | None
    entries: list[EntryView]
    avg_consult: timedelta


def _signal(s: AsyncSession, qs: QueueSession) -> None:
    events.emit(
        s,
        events.clinic_channel(qs.clinic_id),
        {"type": "queue.updated", "queue_session_id": qs.id, "doctor_id": qs.doctor_id},
    )


def _assert_doctor_scope(ctx: RequestContext, doctor_id: uuid.UUID) -> None:
    if ctx.role == "doctor" and ctx.doctor_id != doctor_id:
        raise Forbidden("doctors can only operate their own queue", code="not_own_queue")


async def _clinic(s: AsyncSession, ctx: RequestContext) -> tuple[Clinic, ZoneInfo, ClinicSettings]:
    clinic = await s.get(Clinic, ctx.tenant)
    assert clinic is not None
    return clinic, ZoneInfo(clinic.timezone), ClinicSettings.from_stored(clinic.settings)


async def _templates_on(s: AsyncSession, clinic_id: uuid.UUID, doctor_id: uuid.UUID, day: date) -> list[DoctorSession]:
    off = await s.scalar(
        select(ScheduleException.id).where(
            ScheduleException.clinic_id == clinic_id,
            or_(ScheduleException.doctor_id.is_(None), ScheduleException.doctor_id == doctor_id),
            ScheduleException.start_date <= day,
            ScheduleException.end_date >= day,
        )
    )
    if off is not None:
        return []
    rows = await s.scalars(
        select(DoctorSession)
        .where(DoctorSession.doctor_id == doctor_id, DoctorSession.weekday == day.weekday())
        .order_by(DoctorSession.start_time)
    )
    return list(rows.all())


async def _get_or_create_session(
    s: AsyncSession, clinic_id: uuid.UUID, doctor_id: uuid.UUID, day: date, tmpl: DoctorSession, tz: ZoneInfo
) -> QueueSession:
    starts = datetime.combine(day, tmpl.start_time, tzinfo=tz).astimezone(UTC)
    ends = datetime.combine(day, tmpl.end_time, tzinfo=tz).astimezone(UTC)
    await s.execute(
        insert(QueueSession)
        .values(
            clinic_id=clinic_id,
            doctor_id=doctor_id,
            session_date=day,
            start_time=tmpl.start_time,
            end_time=tmpl.end_time,
            starts_at=starts,
            ends_at=ends,
            max_tokens=tmpl.max_tokens,
        )
        .on_conflict_do_nothing(index_elements=["doctor_id", "session_date", "start_time"])
    )
    qs = await s.scalar(
        select(QueueSession)
        .where(
            QueueSession.doctor_id == doctor_id,
            QueueSession.session_date == day,
            QueueSession.start_time == tmpl.start_time,
        )
        .with_for_update()
    )
    assert qs is not None
    return qs


async def lock_session(s: AsyncSession, ctx: RequestContext, queue_session_id: uuid.UUID) -> QueueSession:
    qs = await s.scalar(
        select(QueueSession)
        .where(QueueSession.id == queue_session_id, QueueSession.clinic_id == ctx.tenant)
        .with_for_update()
    )
    if qs is None:
        raise Forbidden("queue not found in this clinic", code="forbidden_or_not_found")
    _assert_doctor_scope(ctx, qs.doctor_id)
    return qs


def _next_token(qs: QueueSession) -> int:
    qs.last_token_no += 1
    return qs.last_token_no


async def issue_token(
    s: AsyncSession,
    ctx: RequestContext,
    clock: Clock,
    *,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID | None,
    phone: str | None,
    channel: str,
) -> QueueEntry:
    """FR-4.1 walk-in token. Idempotent per patient per session (double taps return the same token)."""
    clinic, tz, rules = await _clinic(s, ctx)
    now = clock.now()
    doctor = await scheduling.get_doctor(s, ctx, doctor_id)
    if not doctor.is_active:
        raise PolicyViolation("doctor is not seeing patients", code="doctor_inactive")
    if patient_id is not None:
        patient = await patients.get_patient(s, ctx, patient_id)
        phone = phone or patient.phone

    today = now.astimezone(tz).date()
    templates = await _templates_on(s, clinic.id, doctor.id, today)
    window = timedelta(minutes=rules.token_window_minutes)
    tmpl = next(
        (
            t
            for t in templates
            if datetime.combine(today, t.start_time, tzinfo=tz) - window
            <= now
            < datetime.combine(today, t.end_time, tzinfo=tz)
        ),
        None,
    )
    if tmpl is None:
        upcoming = next((t for t in templates if datetime.combine(today, t.start_time, tzinfo=tz) > now), None)
        if upcoming is None:
            raise PolicyViolation("no session for this doctor right now", code="no_session")
        starts = datetime.combine(today, upcoming.start_time, tzinfo=tz)
        ends = datetime.combine(today, upcoming.end_time, tzinfo=tz)
        qpolicy.check_token_window(now=now, starts_at=starts, ends_at=ends, window_minutes=rules.token_window_minutes)
        raise AssertionError("unreachable: window check must have raised")  # pragma: no cover

    qs = await _get_or_create_session(s, clinic.id, doctor.id, today, tmpl, tz)
    qpolicy.check_token_window(
        now=now, starts_at=qs.starts_at, ends_at=qs.ends_at, window_minutes=rules.token_window_minutes
    )
    if patient_id is not None:
        existing = await s.scalar(
            select(QueueEntry).where(
                QueueEntry.queue_session_id == qs.id,
                QueueEntry.patient_id == patient_id,
                QueueEntry.status.in_(("waiting", "called")),
            )
        )
        if existing is not None:
            await commit(s)
            return existing
    walk_ins = await s.scalar(
        select(func.count()).where(
            QueueEntry.queue_session_id == qs.id,
            QueueEntry.kind == "walk_in",
            QueueEntry.status != "cancelled",
        )
    )
    qpolicy.check_token_limit(int(walk_ins or 0), max_tokens=qs.max_tokens)

    entry = QueueEntry(
        clinic_id=clinic.id,
        queue_session_id=qs.id,
        token_no=_next_token(qs),
        kind="walk_in",
        status="waiting",
        patient_id=patient_id,
        phone=phone,
        channel=channel,
        public_code=secrets.token_urlsafe(16),
        issued_at=now,
    )
    s.add(entry)
    await s.flush()
    audit.record(
        s,
        ctx,
        "queue.token_issue",
        "queue_entry",
        entry.id,
        after={"token_no": entry.token_no, "queue_session_id": qs.id, "channel": channel},
    )
    _signal(s, qs)
    await commit(s)
    return entry


async def add_arrival(
    s: AsyncSession,
    ctx: RequestContext,
    clock: Clock,
    *,
    appointment_id: uuid.UUID,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    phone: str,
    slot_start: datetime,
) -> QueueEntry | None:
    """Booked patient marked arrived → joins the merged queue (FR-4.6). Joins the caller's transaction."""
    clinic, tz, _ = await _clinic(s, ctx)
    day = slot_start.astimezone(tz).date()
    local_t = slot_start.astimezone(tz).time()
    tmpl = next(
        (t for t in await _templates_on(s, clinic.id, doctor_id, day) if t.start_time <= local_t < t.end_time),
        None,
    )
    if tmpl is None:
        return None  # session removed after booking; arrival still recorded on the appointment
    qs = await _get_or_create_session(s, clinic.id, doctor_id, day, tmpl, tz)
    entry = QueueEntry(
        clinic_id=clinic.id,
        queue_session_id=qs.id,
        token_no=_next_token(qs),
        kind="booked",
        status="waiting",
        appointment_id=appointment_id,
        patient_id=patient_id,
        phone=phone,
        slot_start=slot_start,
        channel="dashboard",
        public_code=secrets.token_urlsafe(16),
        issued_at=clock.now(),
    )
    s.add(entry)
    await s.flush()
    audit.record(
        s,
        ctx,
        "queue.booked_arrival",
        "queue_entry",
        entry.id,
        after={"token_no": entry.token_no, "appointment_id": appointment_id},
    )
    _signal(s, qs)
    return entry


def _item(e: QueueEntry) -> ordering.QueueItem:
    return ordering.QueueItem(
        id=e.id,
        kind=e.kind,  # type: ignore[arg-type]
        status=e.status,  # type: ignore[arg-type]
        issued_at=e.issued_at,
        token_no=e.token_no,
        slot_start=e.slot_start,
        arrived=True,
        priority=e.priority,
    )


async def _entries(s: AsyncSession, qs: QueueSession) -> list[QueueEntry]:
    rows = await s.scalars(select(QueueEntry).where(QueueEntry.queue_session_id == qs.id).order_by(QueueEntry.token_no))
    return list(rows.all())


async def _complete(s: AsyncSession, ctx: RequestContext, clock: Clock, entry: QueueEntry) -> None:
    entry.status = "completed"
    entry.completed_at = clock.now()
    audit.record(s, ctx, "queue.complete", "queue_entry", entry.id, after={"token_no": entry.token_no})
    if entry.appointment_id is not None:
        from clinicdesk.modules.booking import service as booking  # booking imports queue

        await booking.complete_from_queue(s, ctx, clock, entry.appointment_id)


async def call_next(
    s: AsyncSession, ctx: RequestContext, clock: Clock, queue_session_id: uuid.UUID
) -> QueueEntry | None:
    """FR-4.4: finish whoever is with the doctor, then call the next entry by BR-6 ordering."""
    qs = await lock_session(s, ctx, queue_session_id)
    entries = await _entries(s, qs)
    by_id = {e.id: e for e in entries}
    current = by_id.get(qs.current_entry_id) if qs.current_entry_id else None
    if current is not None and current.status == "called":
        await _complete(s, ctx, clock, current)
    nxt_item = ordering.next_item([_item(e) for e in entries if e.status == "waiting"], clock.now())
    nxt = by_id[nxt_item.id] if nxt_item else None
    if nxt is not None:
        nxt.status = "called"
        nxt.called_at = clock.now()
        nxt.priority = False
        audit.record(s, ctx, "queue.call", "queue_entry", nxt.id, after={"token_no": nxt.token_no})
    qs.current_entry_id = nxt.id if nxt else None
    await s.flush()
    await _queue_alerts(s, ctx, clock, qs)
    _signal(s, qs)
    await commit(s)
    return nxt


async def complete_current(s: AsyncSession, ctx: RequestContext, clock: Clock, queue_session_id: uuid.UUID) -> None:
    """Doctor marks the visit done without calling the next patient (e.g. the last one)."""
    qs = await lock_session(s, ctx, queue_session_id)
    if qs.current_entry_id is None:
        raise PolicyViolation("nobody is with the doctor", code="no_current_patient")
    current = await s.get(QueueEntry, qs.current_entry_id, with_for_update=True)
    if current is not None and current.status == "called":
        await _complete(s, ctx, clock, current)
    qs.current_entry_id = None
    _signal(s, qs)
    await commit(s)


async def _lock_entry(
    s: AsyncSession, ctx: RequestContext, entry_id: uuid.UUID, db: Database | None
) -> tuple[QueueEntry, QueueSession]:
    entry = await s.scalar(select(QueueEntry).where(QueueEntry.id == entry_id, QueueEntry.clinic_id == ctx.tenant))
    if entry is None:
        if db is not None:
            await audit.record_now(db, ctx, "access_denied", "queue_entry", entry_id)
        raise Forbidden("token not found in this clinic", code="forbidden_or_not_found")
    qs = await lock_session(s, ctx, entry.queue_session_id)  # session lock first, then the entry
    await s.refresh(entry, with_for_update=True)
    return entry, qs


async def change_entry(
    s: AsyncSession,
    ctx: RequestContext,
    clock: Clock,
    entry_id: uuid.UUID,
    action: str,
    *,
    db: Database | None = None,
) -> QueueEntry:
    """skip | recall | cancel (FR-4.4)."""
    entry, qs = await _lock_entry(s, ctx, entry_id, db)
    allowed = {"skip": ("waiting", "called"), "recall": ("skipped",), "cancel": ("waiting", "skipped")}
    if entry.status not in allowed[action]:
        raise PolicyViolation(f"cannot {action} a {entry.status} token", code="invalid_transition")
    if action == "cancel" and entry.kind == "booked":
        raise PolicyViolation("booked patients leave the queue via the appointment", code="invalid_transition")
    before = entry.status
    if action == "skip":
        entry.status = "skipped"
        if qs.current_entry_id == entry.id:
            qs.current_entry_id = None
    elif action == "recall":
        entry.status, entry.priority = "waiting", True
    else:
        entry.status = "cancelled"
    audit.record(
        s,
        ctx,
        f"queue.{action}",
        "queue_entry",
        entry.id,
        before={"status": before},
        after={"status": entry.status, "token_no": entry.token_no},
    )
    _signal(s, qs)
    await commit(s)
    return entry


async def _avg_consult(s: AsyncSession, doctor_id: uuid.UUID, now: datetime, fallback: timedelta) -> timedelta:
    rows = await s.execute(
        select(QueueEntry.called_at, QueueEntry.completed_at)
        .join(QueueSession, QueueSession.id == QueueEntry.queue_session_id)
        .where(
            QueueSession.doctor_id == doctor_id,
            QueueEntry.status == "completed",
            QueueEntry.called_at.is_not(None),
            QueueEntry.completed_at >= now - timedelta(days=30),
        )
        .limit(2000)
    )
    return qpolicy.average_consult([b - a for a, b in rows.all() if a and b], fallback=fallback)


async def _expected_bookings(s: AsyncSession, qs: QueueSession) -> list[ordering.QueueItem]:
    """Booked patients not yet arrived, for wait projections only (read-only on appointments)."""
    from clinicdesk.modules.booking.models import UPCOMING_STATUSES, Appointment

    rows = await s.scalars(
        select(Appointment).where(
            Appointment.doctor_id == qs.doctor_id,
            Appointment.status.in_(UPCOMING_STATUSES),
            Appointment.slot_start >= qs.starts_at,
            Appointment.slot_start < qs.ends_at,
        )
    )
    return [
        ordering.QueueItem(
            id=a.id,
            kind="booked",
            status="waiting",
            issued_at=a.slot_start,
            slot_start=a.slot_start,
            arrived=False,
        )
        for a in rows.all()
    ]


async def build_snapshot(s: AsyncSession, qs: QueueSession, now: datetime) -> Snapshot:
    from clinicdesk.modules.scheduling.models import Doctor

    doctor = await s.get(Doctor, qs.doctor_id)
    assert doctor is not None
    avg = await _avg_consult(s, qs.doctor_id, now, timedelta(minutes=doctor.slot_minutes))
    entries = await _entries(s, qs)
    current = next((e for e in entries if e.id == qs.current_entry_id), None)
    remaining = None
    if current is not None and current.called_at is not None:
        remaining = max(avg - (now - current.called_at), timedelta(0))
    items = [_item(e) for e in entries if e.status == "waiting"] + await _expected_bookings(s, qs)
    projected = {
        p.item.id: p for p in ordering.project_order(items, now=now, avg_consult=avg, in_consult_remaining=remaining)
    }
    views = [
        EntryView(
            e,
            projected[e.id].ahead if e.id in projected else None,
            projected[e.id].eta if e.id in projected else None,
        )
        for e in entries
    ]
    return Snapshot(qs, current, views, avg)


async def snapshot_for(
    s: AsyncSession, ctx: RequestContext, clock: Clock, doctor_id: uuid.UUID, day: date
) -> list[Snapshot]:
    if ctx.role == "doctor":
        _assert_doctor_scope(ctx, doctor_id)
    await scheduling.get_doctor(s, ctx, doctor_id)
    rows = await s.scalars(
        select(QueueSession)
        .where(
            QueueSession.clinic_id == ctx.tenant,
            QueueSession.doctor_id == doctor_id,
            QueueSession.session_date == day,
        )
        .order_by(QueueSession.start_time)
    )
    now = clock.now()
    return [await build_snapshot(s, qs, now) for qs in rows.all()]


@dataclass(frozen=True, slots=True)
class PublicStatus:
    token_no: int
    status: str
    current_token_no: int | None
    ahead: int | None
    eta: datetime | None
    doctor_name: str


async def public_status(db: Database, clock: Clock, code: str) -> PublicStatus | None:
    """FR-4.2 patient tracking by unguessable link. Returns no personal data of anyone."""
    # The code is the capability; lookup spans tenants so it runs on the bypass path, read-only.
    async with db.session(bypass_rls=True) as s:
        entry = await s.scalar(select(QueueEntry).where(QueueEntry.public_code == code))
        if entry is None:
            return None
        qs = await s.get(QueueSession, entry.queue_session_id)
        assert qs is not None
        snap = await build_snapshot(s, qs, clock.now())
        from clinicdesk.modules.scheduling.models import Doctor

        doctor = await s.get(Doctor, qs.doctor_id)
        view = next(v for v in snap.entries if v.entry.id == entry.id)
        return PublicStatus(
            token_no=entry.token_no,
            status=entry.status,
            current_token_no=snap.current.token_no if snap.current else None,
            ahead=view.ahead,
            eta=view.eta,
            doctor_name=doctor.name if doctor else "",
        )


async def _queue_alerts(s: AsyncSession, ctx: RequestContext, clock: Clock, qs: QueueSession) -> None:
    """FR-4.3: one WhatsApp alert per token when it is `alert_ahead` (default 3) or fewer from its turn."""
    from clinicdesk.modules.messaging import service as messaging
    from clinicdesk.modules.messaging.templates import t, template_ref

    clinic, _, rules = await _clinic(s, ctx)
    now = clock.now()
    snap = await build_snapshot(s, qs, now)
    for view in snap.entries:
        e = view.entry
        if (
            e.status != "waiting"
            or e.phone is None
            or e.alert_sent_at is not None
            or view.ahead is None
            or view.ahead > rules.alert_ahead
        ):
            continue
        lang = await messaging.preferred_language(s, clinic, e.phone)
        params = {"token": e.token_no, "ahead": view.ahead}
        await messaging.queue_message(
            s,
            clinic_id=clinic.id,
            to_phone=e.phone,
            phone_number_id="",
            category="transactional",
            key=f"token_alert:{e.id}",
            run_at=now,
            session={"type": "text", "text": t("token_alert", lang, **params)},
            template=template_ref("token_alert", lang, **params),
            patient_id=e.patient_id,
        )
        e.alert_sent_at = now
