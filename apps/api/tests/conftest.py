"""Shared fixtures. Integration tests run against real PostgreSQL as the RLS-subject runtime role.

Start services first:  docker compose up -d db redis
Integration tests are skipped (never silently passed) when the test database is unreachable.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

API_DIR = Path(__file__).resolve().parents[1]
ROOT = API_DIR.parents[1]


def _env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.split("#", 1)[0].strip()
    values.update({k: v for k, v in os.environ.items() if k.startswith("TEST_")})
    return values


ENV = _env()
TEST_DB_URL = ENV.get("TEST_DATABASE_URL", "")
TEST_MIGRATION_URL = ENV.get("TEST_MIGRATION_DATABASE_URL", "")


def _db_reachable() -> str | None:
    if not TEST_DB_URL or not TEST_MIGRATION_URL:
        return "TEST_DATABASE_URL / TEST_MIGRATION_DATABASE_URL not configured"
    try:
        import psycopg

        dsn = TEST_MIGRATION_URL.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(dsn, connect_timeout=3):
            return None
    except Exception as e:  # pragma: no cover - environment dependent
        return f"test database unreachable: {type(e).__name__}"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not any("integration" in i.keywords for i in items):
        return
    reason = _db_reachable()
    if reason:
        skip = pytest.mark.skip(reason=reason)
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


# --- integration fixtures -----------------------------------------------------------------------

JWT_SECRET = "t" * 40
MONDAY_0900_IST = datetime(2026, 11, 23, 3, 30, tzinfo=UTC)


@pytest.fixture(scope="session")
def migrated() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.attributes["url"] = TEST_MIGRATION_URL
    command.downgrade(cfg, "base")  # also exercises downgrade
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
async def database(migrated: None) -> AsyncIterator[Any]:
    from clinicdesk.core.db import Database

    db = Database(TEST_DB_URL, pool_size=20)
    yield db
    await db.dispose()


@pytest.fixture
def clock() -> Any:
    from clinicdesk.core.clock import FixedClock

    return FixedClock(MONDAY_0900_IST)


@pytest.fixture
def otp_sender() -> Any:
    from clinicdesk.integrations.otp import RecordingOtpSender

    return RecordingOtpSender()


@pytest.fixture
def broker() -> Any:
    from clinicdesk.core.events import MemoryBroker

    return MemoryBroker()


WA_SECRET = "wa-test-app-secret"
SHARED_PNID = "100000000000001"


@pytest.fixture
def whatsapp() -> Any:
    from clinicdesk.integrations.whatsapp import FakeWhatsAppClient

    return FakeWhatsAppClient()


@pytest.fixture
def app(database: Any, clock: Any, otp_sender: Any, broker: Any, whatsapp: Any) -> Any:
    from clinicdesk.core.config import Settings
    from clinicdesk.core.runtime import RecordingWaker
    from clinicdesk.main import create_app

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        env="test",
        database_url=TEST_DB_URL,
        jwt_secret=JWT_SECRET,
        otp_pepper="p" * 40,
        whatsapp_app_secret=WA_SECRET,
        whatsapp_verify_token="verify-me",
        whatsapp_shared_phone_number_id=SHARED_PNID,
        privacy_notice_url="https://clinicdesk.test/privacy",
        public_base_url="https://app.clinicdesk.test",
    )
    return create_app(
        settings,
        clock=clock,
        db=database,
        otp_sender=otp_sender,
        broker=broker,
        whatsapp=whatsapp,
        waker=RecordingWaker(),
    )


@pytest.fixture
def rt(app: Any) -> Any:
    """The app's Runtime (fake WhatsApp, recording waker, memory broker, test clock)."""
    return app.state.runtime


@pytest.fixture
async def client(app: Any) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def rand_phone() -> str:
    return "+919" + str(uuid.uuid4().int)[:9]


def rand_slug() -> str:
    return "C" + uuid.uuid4().hex[:8].upper()


@dataclass
class ClinicFixture:
    clinic_id: str
    owner_user_id: str
    doctor_id: str
    clock: Any
    patient_ids: list[str] = field(default_factory=list)

    @property
    def owner_token(self) -> str:
        """Fresh owner access token at the *test clock's* time, so clock jumps don't expire it."""
        from clinicdesk.core.security import AccessClaims, encode_access_token

        claims = AccessClaims(uuid.UUID(self.owner_user_id), uuid.uuid4(), uuid.UUID(self.clinic_id), "owner", False)
        return encode_access_token(claims, secret=JWT_SECRET, kid="k1", now=self.clock.now(), ttl=timedelta(minutes=15))

    @property
    def h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.owner_token}"}


async def login(client: httpx.AsyncClient, otp_sender: Any, phone: str) -> dict[str, Any]:
    r = await client.post("/api/v1/auth/otp/request", json={"phone": phone})
    assert r.status_code == 202, r.text
    r = await client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": otp_sender.codes[phone]})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def make_clinic(client: httpx.AsyncClient, otp_sender: Any, clock: Any) -> Any:
    """Onboard an owner + clinic + one doctor (Mon–Sat 10:00–13:00, 15-min slots) + N patients."""

    async def _make(patients: int = 2, specialty: str = "dental") -> ClinicFixture:
        tokens = await login(client, otp_sender, rand_phone())
        h = {"Authorization": f"Bearer {tokens['access_token']}"}
        r = await client.post(
            "/api/v1/clinics",
            json={
                "name": "Smile Dental",
                "slug": rand_slug(),
                "specialty": specialty,
                "default_fee_paise": 50000,
            },
            headers=h,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        h = {"Authorization": f"Bearer {body['tokens']['access_token']}"}
        owner_user_id = (await client.get("/api/v1/auth/me", headers=h)).json()["user_id"]
        r = await client.post("/api/v1/doctors", json={"name": "Dr. Shah", "slot_minutes": 15}, headers=h)
        assert r.status_code == 201, r.text
        doctor_id = r.json()["id"]
        sessions = [{"weekday": d, "start_time": "10:00", "end_time": "13:00", "max_tokens": 30} for d in range(6)]
        r = await client.put(f"/api/v1/doctors/{doctor_id}/sessions", json={"sessions": sessions}, headers=h)
        assert r.status_code == 200, r.text
        fx = ClinicFixture(body["clinic"]["id"], owner_user_id, doctor_id, clock)
        for i in range(patients):
            r = await client.post(
                "/api/v1/patients", json={"phone": rand_phone(), "name": f"Patient {i}", "age": 30}, headers=h
            )
            assert r.status_code == 201, r.text
            fx.patient_ids.append(r.json()["id"])
        return fx

    return _make
