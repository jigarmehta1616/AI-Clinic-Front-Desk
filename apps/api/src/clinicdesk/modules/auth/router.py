from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status

from clinicdesk.core.deps import ClockDep, DbDep, PrincipalDep, SettingsDep
from clinicdesk.core.errors import Unauthorized
from clinicdesk.modules.auth import service
from clinicdesk.modules.auth.schemas import Me, OtpRequest, OtpVerify, SelectClinic, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "cd_refresh"
COOKIE_PATH = "/api/v1/auth"


def _respond(response: Response, settings, tokens: service.IssuedTokens) -> TokenResponse:  # type: ignore[no-untyped-def]
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=settings.env in ("staging", "production"),
        samesite="strict",
        path=COOKIE_PATH,
    )
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        clinic_id=tokens.clinic_id,
        role=tokens.role,
        memberships=tokens.memberships,
    )


@router.post("/otp/request", status_code=status.HTTP_202_ACCEPTED)
async def otp_request(
    body: OtpRequest, request: Request, db: DbDep, settings: SettingsDep, clock: ClockDep
) -> dict[str, str]:
    await service.request_otp(db, settings, clock, request.app.state.otp_sender, body.phone)
    return {"status": "sent"}


@router.post("/otp/verify", response_model=TokenResponse)
async def otp_verify(
    body: OtpVerify, response: Response, db: DbDep, settings: SettingsDep, clock: ClockDep
) -> TokenResponse:
    return _respond(response, settings, await service.verify_otp(db, settings, clock, body.phone, body.code))


@router.post("/select-clinic", response_model=TokenResponse)
async def select_clinic(
    body: SelectClinic,
    ctx: PrincipalDep,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> TokenResponse:
    return _respond(response, settings, await service.select_clinic(db, settings, clock, ctx, body.clinic_id))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    clock: ClockDep,
    cd_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    if not cd_refresh:
        raise Unauthorized("missing refresh token", code="refresh_missing")
    return _respond(response, settings, await service.refresh(db, settings, clock, cd_refresh))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response, db: DbDep, clock: ClockDep, cd_refresh: Annotated[str | None, Cookie()] = None
) -> Response:
    if cd_refresh:
        await service.logout(db, clock, cd_refresh)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=Me)
async def me(ctx: PrincipalDep, db: DbDep) -> Me:
    user, memberships = await service.me(db, ctx)
    return Me(
        user_id=user.id,
        phone=user.phone,
        name=user.name,
        clinic_id=ctx.clinic_id,
        role=ctx.role,
        memberships=memberships,
    )
