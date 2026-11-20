"""Staff authentication: OTP sign-in/sign-up (FR-1.1), clinic selection, rotating refresh tokens (NFR-10)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core.clock import Clock
from clinicdesk.core.config import Settings
from clinicdesk.core.context import RequestContext
from clinicdesk.core.db import Database
from clinicdesk.core.errors import Forbidden, RateLimited, Unauthorized
from clinicdesk.core.security import (
    AccessClaims,
    encode_access_token,
    hash_otp,
    hash_token,
    new_otp_code,
    new_refresh_token,
    otp_matches,
)
from clinicdesk.integrations.otp import OtpSender
from clinicdesk.modules.audit import service as audit
from clinicdesk.modules.auth.models import OtpChallenge, RefreshToken
from clinicdesk.modules.auth.schemas import MembershipSummary
from clinicdesk.modules.tenancy.models import Clinic, ClinicMembership, User

# ADR-0007: a rotated refresh token presented again within this window is a benign race (reload during
# refresh, two tabs), not theft. After it, reuse revokes the whole token family.
REUSE_GRACE = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    clinic_id: uuid.UUID | None
    role: str | None
    memberships: list[MembershipSummary]


def _anon(phone_ctx: str | None = None) -> RequestContext:
    return RequestContext("anonymous", None, None, None, "dashboard", phone_ctx)


async def request_otp(
    db: Database, settings: Settings, clock: Clock, sender: OtpSender, phone: str
) -> None:
    now = clock.now()
    async with db.session() as s:
        window_start = now - timedelta(seconds=settings.otp_send_window_seconds)
        # Serialise concurrent requests for one phone so the rate limit can't be raced.
        await s.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended("otp:" + phone, 0)))
        )
        sent = await s.scalar(
            select(func.count()).where(
                OtpChallenge.phone == phone, OtpChallenge.created_at >= window_start
            )
        )
        if (sent or 0) >= settings.otp_max_sends_per_window:
            raise RateLimited(
                "too many OTP requests, try again later", code="otp_rate_limited"
            )
        code = new_otp_code()
        s.add(
            OtpChallenge(
                phone=phone,
                code_hash=hash_otp(phone, code, settings.otp_pepper),
                expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
                created_at=now,
            )
        )
        await s.commit()
        print(f"OTP for {phone}: {code}")  # TODO: remove this debug print
    await sender.send(phone, code)


async def _memberships(
    s: AsyncSession, user_id: uuid.UUID
) -> list[tuple[ClinicMembership, Clinic]]:
    rows = await s.execute(
        select(ClinicMembership, Clinic)
        .join(Clinic, Clinic.id == ClinicMembership.clinic_id)
        .where(
            ClinicMembership.user_id == user_id, ClinicMembership.status != "disabled"
        )
        .order_by(Clinic.name)
    )
    return [(m, c) for m, c in rows.all()]


async def _issue(
    s: AsyncSession,
    settings: Settings,
    clock: Clock,
    user: User,
    membership: ClinicMembership | None,
    memberships: list[MembershipSummary],
    family_id: uuid.UUID | None = None,
) -> IssuedTokens:
    now = clock.now()
    family_id = family_id or uuid.uuid4()
    refresh = new_refresh_token()
    s.add(
        RefreshToken(
            user_id=user.id,
            clinic_id=membership.clinic_id if membership else None,
            family_id=family_id,
            token_hash=hash_token(refresh),
            expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    claims = AccessClaims(
        user_id=user.id,
        session_family=family_id,
        clinic_id=membership.clinic_id if membership else None,
        role=membership.role if membership else None,
        is_platform_admin=user.is_platform_admin,
        doctor_id=membership.doctor_id if membership else None,
    )
    access = encode_access_token(
        claims, secret=settings.jwt_secret, kid=settings.jwt_kid, now=now, ttl=ttl
    )
    return IssuedTokens(
        access,
        refresh,
        int(ttl.total_seconds()),
        claims.clinic_id,
        claims.role,
        memberships,
    )


def _summaries(rows: list[tuple[ClinicMembership, Clinic]]) -> list[MembershipSummary]:
    return [
        MembershipSummary(clinic_id=c.id, clinic_name=c.name, role=m.role)
        for m, c in rows
    ]


async def verify_otp(
    db: Database, settings: Settings, clock: Clock, phone: str, code: str
) -> IssuedTokens:
    now = clock.now()
    async with db.session() as s:
        challenge = await s.scalar(
            select(OtpChallenge)
            .where(
                OtpChallenge.phone == phone,
                OtpChallenge.consumed_at.is_(None),
                OtpChallenge.expires_at > now,
            )
            .order_by(OtpChallenge.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if challenge is None or challenge.attempts >= settings.otp_max_attempts:
            raise Unauthorized("invalid or expired code", code="otp_invalid")
        challenge.attempts += 1
        if not otp_matches(phone, code, settings.otp_pepper, challenge.code_hash):
            await s.commit()  # persist the failed attempt
            raise Unauthorized("invalid or expired code", code="otp_invalid")
        challenge.consumed_at = now

        user = await s.scalar(select(User).where(User.phone == phone))
        if user is None:  # first sign-in = sign-up (FR-1.1)
            user = User(phone=phone)
            s.add(user)
            await s.flush()
            audit.record(
                s,
                RequestContext("user", user.id, None, None, "dashboard"),
                "user.signup",
                "user",
                user.id,
            )
        elif not user.is_active:
            raise Forbidden("account disabled", code="account_disabled")
        await s.commit()

    # Membership lookup runs with the user's id so RLS lets them see only their own memberships.
    async with db.session(user_id=user.id) as s:
        rows = await _memberships(s, user.id)
        chosen = rows[0][0] if len(rows) == 1 else None
        tokens = await _issue(s, settings, clock, user, chosen, _summaries(rows))
        audit.record(
            s,
            RequestContext(
                "user", user.id, None, None, "dashboard"
            ),  # platform-level row
            "auth.login",
            "user",
            user.id,
        )
        await s.commit()
    if any(m.status == "invited" for m, _ in rows):
        await _activate_invites(db, user.id)
    return tokens


async def _activate_invites(db: Database, user_id: uuid.UUID) -> None:
    # Audited platform path: the user has no clinic context yet, so RLS bypass is required.
    async with db.session(user_id=user_id, bypass_rls=True) as s:
        await s.execute(
            update(ClinicMembership)
            .where(
                ClinicMembership.user_id == user_id,
                ClinicMembership.status == "invited",
            )
            .values(status="active")
        )
        await s.commit()


async def select_clinic(
    db: Database,
    settings: Settings,
    clock: Clock,
    ctx: RequestContext,
    clinic_id: uuid.UUID,
) -> IssuedTokens:
    async with db.session(user_id=ctx.actor_id) as s:
        rows = await _memberships(s, ctx.actor_id)  # type: ignore[arg-type]
        match = next((m for m, _ in rows if m.clinic_id == clinic_id), None)
        if match is None:
            raise Forbidden("not a member of this clinic", code="not_a_member")
        user = await s.get(User, ctx.actor_id)
        assert user is not None
        tokens = await _issue(s, settings, clock, user, match, _summaries(rows))
        await s.commit()
        return tokens


async def issue_for_membership(
    db: Database,
    settings: Settings,
    clock: Clock,
    user_id: uuid.UUID,
    clinic_id: uuid.UUID,
) -> IssuedTokens:
    """Used right after onboarding creates a clinic."""
    async with db.session(user_id=user_id, clinic_id=clinic_id) as s:
        rows = await _memberships(s, user_id)
        match = next(m for m, _ in rows if m.clinic_id == clinic_id)
        user = await s.get(User, user_id)
        assert user is not None
        tokens = await _issue(s, settings, clock, user, match, _summaries(rows))
        await s.commit()
        return tokens


async def refresh(
    db: Database, settings: Settings, clock: Clock, token: str
) -> IssuedTokens:
    now = clock.now()
    async with db.session() as s:
        row = await s.scalar(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(token))
            .with_for_update()
        )
        if row is None:
            raise Unauthorized("invalid refresh token", code="refresh_invalid")
        if row.revoked_at is not None:
            raise Unauthorized(
                "session has ended, please sign in again", code="refresh_revoked"
            )
        in_grace = row.rotated_at is not None and now - row.rotated_at <= REUSE_GRACE
        if row.rotated_at is not None and not in_grace:
            # Reuse of a spent token → assume theft, revoke the whole family (ADR-0007).
            await s.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.family_id == row.family_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            audit.record(
                s,
                RequestContext(
                    "user", row.user_id, None, None, "dashboard"
                ),  # platform-level row
                "auth.refresh_reuse_detected",
                "refresh_family",
                row.family_id,
            )
            await s.commit()
            raise Unauthorized("refresh token reuse detected", code="refresh_reused")
        if row.expires_at <= now:
            raise Unauthorized("refresh token expired", code="refresh_expired")
        # Benign race (page reloaded mid-refresh, two tabs): within the grace window the spent token yields a
        # fresh token in the same family instead of revoking it. Keep the original rotation time.
        row.rotated_at = row.rotated_at or now
        user_id, clinic_id, family_id = row.user_id, row.clinic_id, row.family_id
        await s.commit()

    async with db.session(user_id=user_id) as s:
        user = await s.get(User, user_id)
        if user is None or not user.is_active:
            raise Unauthorized("account disabled", code="account_disabled")
        rows = await _memberships(s, user_id)
        match = (
            next((m for m, _ in rows if m.clinic_id == clinic_id), None)
            if clinic_id
            else None
        )
        if clinic_id and match is None:  # membership removed since login
            raise Unauthorized("membership no longer active", code="membership_revoked")
        tokens = await _issue(
            s, settings, clock, user, match, _summaries(rows), family_id=family_id
        )
        await s.commit()
        return tokens


async def logout(db: Database, clock: Clock, token: str) -> None:
    async with db.session() as s:
        row = await s.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(token))
        )
        if row is not None:
            await s.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.family_id == row.family_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=clock.now())
            )
            await s.commit()


async def me(db: Database, ctx: RequestContext) -> tuple[User, list[MembershipSummary]]:
    async with db.session(user_id=ctx.actor_id, clinic_id=ctx.clinic_id) as s:
        user = await s.get(User, ctx.actor_id)
        if user is None:
            raise Unauthorized("unknown user")
        return user, _summaries(await _memberships(s, user.id))
