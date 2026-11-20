"""FastAPI dependencies: settings, clock, database, authenticated context, permissions, tenant session."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from clinicdesk.core import events
from clinicdesk.core.clock import Clock
from clinicdesk.core.config import Settings
from clinicdesk.core.context import RequestContext
from clinicdesk.core.db import Database
from clinicdesk.core.errors import Forbidden, Unauthorized
from clinicdesk.core.rbac import Permission, has_permission
from clinicdesk.core.security import decode_access_token


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_clock(request: Request) -> Clock:
    return request.app.state.clock  # type: ignore[no-any-return]


def get_db(request: Request) -> Database:
    return request.app.state.db  # type: ignore[no-any-return]


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ClockDep = Annotated[Clock, Depends(get_clock)]
DbDep = Annotated[Database, Depends(get_db)]


async def get_principal(
    request: Request,
    settings: SettingsDep,
    clock: ClockDep,
    authorization: Annotated[str | None, Header()] = None,
) -> RequestContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("missing bearer token")
    try:
        claims = decode_access_token(authorization[7:].strip(), secret=settings.jwt_secret, now=clock.now())
    except jwt.InvalidTokenError as e:
        raise Unauthorized("invalid or expired token") from e
    return RequestContext(
        actor_type="user",
        actor_id=claims.user_id,
        clinic_id=claims.clinic_id,
        role=claims.role,
        channel="dashboard",
        request_id=getattr(request.state, "request_id", None),
        doctor_id=claims.doctor_id,
        is_platform_admin=claims.is_platform_admin,
    )


PrincipalDep = Annotated[RequestContext, Depends(get_principal)]


def require(perm: Permission) -> Callable[..., Coroutine[Any, Any, RequestContext]]:
    async def _dep(ctx: PrincipalDep, db: DbDep) -> RequestContext:
        if ctx.clinic_id is None:
            raise Forbidden("select a clinic first", code="no_clinic_selected")
        if not has_permission(ctx.role, perm):
            raise Forbidden(f"role {ctx.role} lacks {perm.value}", code="permission_denied")
        if perm != Permission.CLINIC_READ:  # a suspended clinic can still see why (profile + usage)
            from clinicdesk.modules.admin.service import clinic_status  # core must not import modules at load

            if await clinic_status(db, ctx.clinic_id) == "suspended":
                raise Forbidden(
                    "this clinic's account is suspended — contact ClinicDesk support", code="clinic_suspended"
                )
        return ctx

    return _dep


async def tenant_session(ctx: PrincipalDep, db: DbDep, request: Request) -> AsyncIterator[AsyncSession]:
    """Session scoped (RLS) to the caller's clinic. Services commit explicitly; committed live-update
    signals are published when the request finishes (core/events.py)."""
    async with db.session(clinic_id=ctx.clinic_id, user_id=ctx.actor_id) as s:
        yield s
        rt = request.app.state.runtime
        await events.flush(s, rt.broker)
        from clinicdesk.modules.jobs.service import flush_wakes  # core must not import modules at load time

        await flush_wakes(s, rt.waker)


SessionDep = Annotated[AsyncSession, Depends(tenant_session)]
