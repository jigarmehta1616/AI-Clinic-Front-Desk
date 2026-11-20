"""FastAPI application factory."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

import clinicdesk.handlers  # noqa: F401  registers background job handlers
from clinicdesk.core.clock import Clock, SystemClock
from clinicdesk.core.config import Settings, get_settings
from clinicdesk.core.db import Database
from clinicdesk.core.errors import DomainError
from clinicdesk.core.events import Broker, RedisBroker
from clinicdesk.core.logging import configure_logging, log
from clinicdesk.core.realtime import router as ws_router
from clinicdesk.core.runtime import LazyArqWaker, Runtime, Waker
from clinicdesk.integrations.otp import ConsoleOtpSender, OtpSender
from clinicdesk.integrations.whatsapp import CloudApiClient, LoggingWhatsAppClient
from clinicdesk.modules.admin.router import router as admin_router
from clinicdesk.modules.audit.router import router as audit_router
from clinicdesk.modules.auth.router import router as auth_router
from clinicdesk.modules.booking.router import router as booking_router
from clinicdesk.modules.calls.router import router as calls_router
from clinicdesk.modules.dashboard.router import router as dashboard_router
from clinicdesk.modules.inbox.router import router as inbox_router
from clinicdesk.modules.messaging.webhook import router as webhook_router
from clinicdesk.modules.patients.router import router as patients_router
from clinicdesk.modules.queue.router import public_router as queue_public_router
from clinicdesk.modules.queue.router import router as queue_router
from clinicdesk.modules.recall.router import router as recall_router
from clinicdesk.modules.scheduling.router import router as scheduling_router
from clinicdesk.modules.tenancy.router import router as tenancy_router


def _otp_sender(settings: Settings) -> OtpSender:
    if settings.otp_provider == "console":
        return ConsoleOtpSender()
    raise RuntimeError(f"OTP provider {settings.otp_provider!r} is not implemented yet (Phase 4)")


def whatsapp_client(settings: Settings) -> Any:
    if settings.whatsapp_provider == "cloud":
        return CloudApiClient(settings.whatsapp_access_token, settings.whatsapp_api_version)
    return LoggingWhatsAppClient()  # dev only; Settings refuses this in production


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    db: Database | None = None,
    otp_sender: OtpSender | None = None,
    broker: Broker | None = None,
    whatsapp: Any = None,
    waker: Waker | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        lazy = None
        if app.state.runtime.waker is None and settings.env != "test":
            # Instant job wake-ups (NFR-1). Connects lazily and self-heals if Redis was down at startup;
            # meanwhile the worker's 1-minute tick still delivers every job.
            lazy = LazyArqWaker(settings.redis_url, app.state.clock)
            app.state.runtime.waker = lazy
        yield
        if lazy is not None:
            await lazy.close()
        if owns_db:
            await app.state.db.dispose()
        if owns_broker and hasattr(app.state.broker, "close"):
            await app.state.broker.close()

    owns_db = db is None
    owns_broker = broker is None
    app = FastAPI(title="ClinicDesk AI API", version="0.1.0", lifespan=lifespan, openapi_url="/api/v1/openapi.json")
    app.state.settings = settings
    app.state.clock = clock or SystemClock()
    app.state.db = db or Database(settings.database_url)
    app.state.otp_sender = otp_sender or _otp_sender(settings)
    app.state.broker = broker or RedisBroker(settings.redis_url)
    app.state.runtime = Runtime(
        settings=settings,
        db=app.state.db,
        clock=app.state.clock,
        whatsapp=whatsapp or whatsapp_client(settings),
        waker=waker,
        broker=app.state.broker,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid[:64]
        structlog.contextvars.bind_contextvars(request_id=request.state.request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        if exc.status_code >= 500:
            log.error("domain_error", code=exc.code)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "invalid request",
                    "details": {"errors": errors},
                }
            },
        )

    api = APIRouter(prefix="/api/v1")
    for r in (
        auth_router,
        tenancy_router,
        scheduling_router,
        patients_router,
        booking_router,
        queue_router,
        queue_public_router,
        inbox_router,
        dashboard_router,
        calls_router,
        admin_router,
        recall_router,
        webhook_router,
        audit_router,
        ws_router,
    ):
        api.include_router(r)

    @api.get("/health", tags=["ops"])
    async def health(request: Request) -> dict[str, str]:
        async with request.app.state.db.session() as s:
            await s.execute(text("SELECT 1"))
        return {"status": "ok"}

    app.include_router(api)
    return app
