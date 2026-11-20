"""Recall engine (FR-6.1–6.5, FR-1.6, BR-8).

Creation:  visit completed → active treatment plan? count the session, recall the next one (plan-based)
           → else rule for the visit type? recall at visit date + delay.
           Doctor/receptionist can also set a follow-up explicitly with one tap (FR-6.2).
Sending:   job `recall.send` per step; re-checks booking, consent/opt-out, the 3-day cap and quiet hours.
Closing:   booked via the recall button → `booked`; "Not now" → `declined`; no reply → `lapsed`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core.clock import Clock
from clinicdesk.core.context import RequestContext
from clinicdesk.core.db import commit
from clinicdesk.core.errors import PolicyViolation
from clinicdesk.modules.audit import service as audit
from clinicdesk.modules.booking.models import ACTIVE_STATUSES, Appointment
from clinicdesk.modules.jobs import service as jobs
from clinicdesk.modules.messaging import service as messaging
from clinicdesk.modules.messaging.models import OutboxMessage
from clinicdesk.modules.messaging.quiet_hours import adjust_send_time
from clinicdesk.modules.messaging.templates import t, template_ref
from clinicdesk.modules.patients.models import Patient
from clinicdesk.modules.recall import policy
from clinicdesk.modules.recall.models import Recall, RecallRule, TreatmentPlan
from clinicdesk.modules.tenancy.models import Clinic
from clinicdesk.modules.tenancy.schemas import ClinicSettings, Strict


# ------------------------------------------------------------------------------------------ rules
async def seed_rules(s: AsyncSession, clinic_id: uuid.UUID, specialty: str) -> None:
    """FR-1.6: specialty template pre-fills recall rules (idempotent)."""
    for r in policy.SPECIALTY_RULES.get(specialty, []):
        await s.execute(
            insert(RecallRule)
            .values(clinic_id=clinic_id, followup_days=[3, 7], **r)
            .on_conflict_do_nothing(index_elements=["clinic_id", "visit_type"])
        )


class RuleIn(Strict):
    label: str = Field(min_length=2, max_length=80)
    delay_days: int = Field(ge=1, le=730)
    followup_days: list[int] = Field(default_factory=lambda: [3, 7], max_length=2)
    plan_based: bool = False
    is_active: bool = True

    @model_validator(mode="after")
    def _ordered(self) -> RuleIn:
        if any(d < 1 or d > 60 for d in self.followup_days) or self.followup_days != sorted(set(self.followup_days)):
            raise ValueError("followup_days must be increasing values between 1 and 60")
        return self


async def list_rules(s: AsyncSession, ctx: RequestContext) -> list[RecallRule]:
    rows = await s.scalars(select(RecallRule).where(RecallRule.clinic_id == ctx.tenant).order_by(RecallRule.visit_type))
    return list(rows.all())


async def upsert_rule(s: AsyncSession, ctx: RequestContext, visit_type: str, body: RuleIn) -> RecallRule:
    values = body.model_dump()
    await s.execute(
        insert(RecallRule)
        .values(clinic_id=ctx.tenant, visit_type=visit_type, **values)
        .on_conflict_do_update(index_elements=["clinic_id", "visit_type"], set_=values)
    )
    audit.record(s, ctx, "recall_rule.upsert", "recall_rule", visit_type, after=values)
    await commit(s)
    rule = await s.scalar(
        select(RecallRule).where(RecallRule.clinic_id == ctx.tenant, RecallRule.visit_type == visit_type)
    )
    assert rule is not None
    return rule


# ------------------------------------------------------------------------------------------ creation
async def _clinic_tz(s: AsyncSession, clinic_id: uuid.UUID) -> tuple[Clinic, ZoneInfo]:
    clinic = await s.get(Clinic, clinic_id)
    assert clinic is not None
    return clinic, ZoneInfo(clinic.timezone)


async def create_recall(
    s: AsyncSession,
    ctx: RequestContext,
    *,
    appt: Appointment | None,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    label: str,
    due: date,
    visit_type: str | None,
    now: datetime,
    rule: RecallRule | None = None,
    plan: TreatmentPlan | None = None,
) -> Recall | None:
    """Idempotent per source appointment (a re-run hook returns None)."""
    _, tz = await _clinic_tz(s, ctx.tenant)
    recall_id = await s.scalar(
        insert(Recall)
        .values(
            clinic_id=ctx.tenant,
            patient_id=patient_id,
            doctor_id=doctor_id,
            rule_id=rule.id if rule else None,
            plan_id=plan.id if plan else None,
            source_appointment_id=appt.id if appt else None,
            visit_type=visit_type,
            label=label,
            due_date=due,
            followup_days=list(rule.followup_days) if rule else [3, 7],
            created_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=["source_appointment_id"], index_where=Recall.source_appointment_id.is_not(None)
        )
        .returning(Recall.id)
    )
    if recall_id is None:
        return None
    await jobs.enqueue(
        s,
        clinic_id=ctx.tenant,
        kind="recall.send",
        run_at=policy.recall_send_at(due, tz),
        dedup_key=f"recall:{recall_id}:0",
        payload={"recall_id": str(recall_id)},
    )
    audit.record(s, ctx, "recall.schedule", "recall", recall_id, after={"due_date": due, "label": label})
    return await s.get(Recall, recall_id)


async def on_visit_completed(s: AsyncSession, ctx: RequestContext, appt: Appointment, now: datetime) -> None:
    """Hook from booking when an appointment becomes `completed` (joins the caller's transaction)."""
    _, tz = await _clinic_tz(s, ctx.tenant)
    visit_day = now.astimezone(tz).date()
    plan = await s.scalar(
        select(TreatmentPlan)
        .where(
            TreatmentPlan.patient_id == appt.patient_id,
            TreatmentPlan.doctor_id == appt.doctor_id,
            TreatmentPlan.status == "active",
        )
        .with_for_update()
    )
    if plan is not None:
        plan.sessions_done += 1
        if plan.sessions_done >= plan.sessions_planned:
            plan.status = "completed"
            audit.record(s, ctx, "plan.completed", "treatment_plan", plan.id)
            return
        label = f"Session {plan.sessions_done + 1} of {plan.sessions_planned}"
        await create_recall(
            s,
            ctx,
            appt=appt,
            now=now,
            patient_id=appt.patient_id,
            doctor_id=appt.doctor_id,
            label=label,
            due=visit_day + timedelta(days=plan.interval_days),
            visit_type=plan.visit_type,
            plan=plan,
        )
        return
    if appt.visit_type is None:
        return
    rule = await s.scalar(
        select(RecallRule).where(
            RecallRule.clinic_id == ctx.tenant,
            RecallRule.visit_type == appt.visit_type,
            RecallRule.is_active.is_(True),
            RecallRule.plan_based.is_(False),
        )
    )
    if rule is not None:
        await create_recall(
            s,
            ctx,
            appt=appt,
            now=now,
            patient_id=appt.patient_id,
            doctor_id=appt.doctor_id,
            label=rule.label,
            due=policy.recall_due_date(visit_day, rule.delay_days),
            visit_type=rule.visit_type,
            rule=rule,
        )


class FollowupIn(Strict):
    """One-tap follow-ups (FR-6.2): 'Review in 7 days', 'Recall in 6 months', 'Plan: 10 sessions'."""

    kind: Literal["days", "rule", "plan"]
    days: int | None = Field(default=None, ge=1, le=730)
    visit_type: str | None = Field(default=None, pattern=r"^[a-z_]{2,40}$")
    sessions: int | None = Field(default=None, ge=2, le=100)
    interval_days: int | None = Field(default=None, ge=1, le=60)
    label: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _fields(self) -> FollowupIn:
        need = {"days": ["days"], "rule": ["visit_type"], "plan": ["sessions"]}[self.kind]
        if any(getattr(self, f) is None for f in need):
            raise ValueError(f"{self.kind} follow-up needs {', '.join(need)}")
        return self


async def set_followup(
    s: AsyncSession, ctx: RequestContext, clock: Clock, appointment_id: uuid.UUID, body: FollowupIn
) -> dict[str, Any]:
    from clinicdesk.modules.booking import service as booking  # booking imports recall

    appt = await booking.get_for_update(s, ctx, appointment_id)
    if ctx.role == "doctor" and ctx.doctor_id != appt.doctor_id:
        raise PolicyViolation("doctors set follow-ups for their own patients", code="not_own_appointment")
    if appt.status not in ("arrived", "completed"):
        raise PolicyViolation("follow-ups are set after the visit", code="visit_not_done")
    _, tz = await _clinic_tz(s, ctx.tenant)
    now = clock.now()
    today = now.astimezone(tz).date()
    # Replace an automatic recall from this visit with the explicit one.
    existing = await s.scalar(select(Recall).where(Recall.source_appointment_id == appt.id).with_for_update())
    if existing is not None and existing.status == "scheduled":
        existing.status, existing.closed_reason, existing.source_appointment_id = "cancelled", "replaced", None
        await s.flush()
    if body.kind == "plan":
        rule = await s.scalar(
            select(RecallRule).where(RecallRule.clinic_id == ctx.tenant, RecallRule.plan_based.is_(True))
        )
        plan = TreatmentPlan(
            clinic_id=ctx.tenant,
            patient_id=appt.patient_id,
            doctor_id=appt.doctor_id,
            visit_type=body.visit_type or (rule.visit_type if rule else "session"),
            sessions_planned=body.sessions or 1,
            # The current visit counts exactly once: now if already completed, otherwise when it completes.
            sessions_done=1 if appt.status == "completed" else 0,
            interval_days=body.interval_days or (rule.delay_days if rule else 2),
        )
        old = await s.scalar(
            select(TreatmentPlan).where(
                TreatmentPlan.patient_id == appt.patient_id,
                TreatmentPlan.doctor_id == appt.doctor_id,
                TreatmentPlan.status == "active",
            )
        )
        if old is not None:
            old.status = "cancelled"
            await s.flush()
        s.add(plan)
        await s.flush()
        recall = await create_recall(
            s,
            ctx,
            appt=appt,
            now=now,
            patient_id=appt.patient_id,
            doctor_id=appt.doctor_id,
            label=body.label or f"Session 2 of {plan.sessions_planned}",
            due=today + timedelta(days=plan.interval_days),
            visit_type=plan.visit_type,
            plan=plan,
        )
        audit.record(
            s,
            ctx,
            "plan.create",
            "treatment_plan",
            plan.id,
            after={"sessions": plan.sessions_planned, "interval_days": plan.interval_days},
        )
    else:
        rule = None
        if body.kind == "rule":
            rule = await s.scalar(
                select(RecallRule).where(RecallRule.clinic_id == ctx.tenant, RecallRule.visit_type == body.visit_type)
            )
            if rule is None:
                raise PolicyViolation("no recall rule for that visit type", code="unknown_visit_type")
        days = body.days if body.kind == "days" else rule.delay_days  # type: ignore[union-attr]
        recall = await create_recall(
            s,
            ctx,
            appt=appt,
            now=now,
            patient_id=appt.patient_id,
            doctor_id=appt.doctor_id,
            label=body.label or (rule.label if rule else f"Review in {days} days"),
            due=today + timedelta(days=days or 1),
            visit_type=body.visit_type,
            rule=rule,
        )
    await commit(s)
    assert recall is not None
    return {"recall_id": recall.id, "due_date": recall.due_date, "label": recall.label}


# ------------------------------------------------------------------------------------------ sending
async def _close(s: AsyncSession, ctx: RequestContext, r: Recall, status: str, reason: str) -> None:
    r.status, r.closed_reason = status, reason
    audit.record(s, ctx, f"recall.{status}", "recall", r.id, after={"reason": reason})


async def send_recall(jc: jobs.JobContext) -> None:
    from clinicdesk.core.context import system_context

    s, now = jc.s, jc.rt.clock.now()
    r = await s.scalar(select(Recall).where(Recall.id == uuid.UUID(jc.job.payload["recall_id"])).with_for_update())
    if r is None or r.status not in ("scheduled", "sent"):
        return
    ctx = system_context(r.clinic_id)
    clinic, tz = await _clinic_tz(s, r.clinic_id)
    patient = await s.get(Patient, r.patient_id)
    assert patient is not None

    # Any visit booked after this recall was created (upcoming or already attended) makes it unnecessary.
    rebooked = await s.scalar(
        select(Appointment.id)
        .where(
            Appointment.patient_id == r.patient_id,
            Appointment.doctor_id == r.doctor_id,
            Appointment.status.in_(ACTIVE_STATUSES),
            Appointment.created_at >= r.created_at,
        )
        .limit(1)
    )
    if rebooked is not None:
        return await _close(s, ctx, r, "cancelled", "already_booked")
    if r.sends >= policy.max_sends(r.followup_days):
        return await _close(s, ctx, r, "lapsed", "no_reply")  # FR-6.4
    if await messaging.opted_out(s, clinic.id, patient.phone):
        return await _close(s, ctx, r, "skipped", "opted_out")
    if not await messaging.has_consent(s, clinic.id, patient.phone, "recalls"):
        return await _close(s, ctx, r, "skipped", "no_consent")

    last = await s.scalar(
        select(func.max(func.coalesce(OutboxMessage.sent_at, OutboxMessage.created_at))).where(
            OutboxMessage.clinic_id == clinic.id,
            OutboxMessage.to_phone == patient.phone,
            OutboxMessage.category == "recall",
            OutboxMessage.status.in_(("pending", "sending", "sent")),
        )
    )
    deferral = policy.cap_deferral(last, now)  # BR-8
    if deferral is not None:
        raise jobs.Reschedule(deferral, "recall_cap_3_days")
    rules = ClinicSettings.from_stored(clinic.settings)
    allowed = adjust_send_time(now, "recall", tz=tz, start=rules.quiet_start, end=rules.quiet_end)
    if allowed is not None and allowed > now:
        raise jobs.Reschedule(allowed, "quiet_hours")  # BR-7

    lang = await messaging.preferred_language(s, clinic, patient.phone)
    params = {"clinic": clinic.name, "label": r.label}
    ids = [f"recall:{r.id}", f"recall_no:{r.id}"]
    await messaging.queue_message(
        s,
        clinic_id=clinic.id,
        to_phone=patient.phone,
        phone_number_id="",
        category="recall",
        key=f"recall_msg:{r.id}:{r.sends}",
        run_at=now,
        patient_id=patient.id,
        session={
            "type": "buttons",
            "text": t("recall_due", lang, **params),
            "buttons": [
                {"id": ids[0], "title": t("btn_book_now", lang)},
                {"id": ids[1], "title": t("btn_not_now", lang)},
            ],
        },
        template={**template_ref("recall_due", lang, **params), "quick_replies": ids},
    )
    r.sends += 1
    r.first_sent_at = r.first_sent_at or now
    r.last_sent_at = now
    r.status = "sent"
    audit.record(s, ctx, "recall.sent", "recall", r.id, after={"send": r.sends})
    _, at = policy.next_step(
        sends=r.sends, first_sent_at=r.first_sent_at, last_sent_at=now, followup_days=list(r.followup_days)
    )
    await jobs.enqueue(
        s,
        clinic_id=clinic.id,
        kind="recall.send",
        run_at=at,
        dedup_key=f"recall:{r.id}:{r.sends}",
        payload={"recall_id": str(r.id)},
    )


jobs.handler("recall.send")(send_recall)


async def recall_for_phone(s: AsyncSession, clinic_id: uuid.UUID, phone: str, recall_id: uuid.UUID) -> Recall | None:
    return await s.scalar(
        select(Recall)
        .join(Patient, Patient.id == Recall.patient_id)
        .where(Recall.id == recall_id, Recall.clinic_id == clinic_id, Patient.phone == phone)
        .with_for_update()
    )


async def mark_booked(s: AsyncSession, ctx: RequestContext, recall_id: uuid.UUID, appointment_id: uuid.UUID) -> None:
    r = await s.scalar(select(Recall).where(Recall.id == recall_id, Recall.clinic_id == ctx.tenant).with_for_update())
    if r is not None and r.status in ("scheduled", "sent"):
        r.status, r.booked_appointment_id, r.closed_reason = "booked", appointment_id, None
        audit.record(s, ctx, "recall.booked", "recall", r.id, after={"appointment_id": appointment_id})


async def decline(s: AsyncSession, ctx: RequestContext, r: Recall) -> None:
    if r.status in ("scheduled", "sent"):
        await _close(s, ctx, r, "declined", "patient_declined")


async def list_recalls(
    s: AsyncSession, ctx: RequestContext, status: str | None, limit: int = 200, patient_id: uuid.UUID | None = None
) -> list[Recall]:
    q = select(Recall).where(Recall.clinic_id == ctx.tenant).order_by(Recall.due_date).limit(limit)
    if status:
        q = q.where(Recall.status == status)
    if patient_id:
        q = q.where(Recall.patient_id == patient_id)
    return list((await s.scalars(q)).all())
