"""Database engine, declarative base and tenant-scoped sessions (ADR-0002).

Every transaction begun on a session automatically sets the transaction-local Postgres settings
`app.clinic_id`, `app.user_id` and `app.bypass_rls` from `session.info`. Because `set_config(..., true)`
is transaction-local, pooled connections never carry tenant context between requests, and code
that commits mid-operation is re-scoped on the next transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, event, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


_SET_CONTEXT = text(
    "SELECT set_config('app.clinic_id', :clinic_id, true), "
    "set_config('app.user_id', :user_id, true), "
    "set_config('app.bypass_rls', :bypass, true)"
)


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(session: Session, _transaction: Any, connection: Any) -> None:
    info = session.info
    connection.execute(
        _SET_CONTEXT,
        {
            "clinic_id": str(info["clinic_id"]) if info.get("clinic_id") else "",
            "user_id": str(info["user_id"]) if info.get("user_id") else "",
            "bypass": "on" if info.get("bypass_rls") else "off",
        },
    )


async def commit(s: Any) -> None:
    """Commit, unless the caller owns the transaction (`session.info["unit_of_work"]`, e.g. the WhatsApp
    assistant handling one message as one atomic turn) — then only flush."""
    if s.info.get("unit_of_work"):
        await s.flush()
    else:
        await s.commit()


class Database:
    def __init__(self, url: str, *, pool_size: int = 10) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_size=pool_size, pool_pre_ping=True)
        self._factory = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(
        self,
        *,
        clinic_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        bypass_rls: bool = False,
    ) -> AsyncIterator[AsyncSession]:
        """Session whose transactions are scoped to `clinic_id`.

        `bypass_rls=True` is reserved for audited platform code paths (sign-up, login membership
        lookup, cross-tenant jobs). Never pass it from request handlers acting for a clinic.
        """
        async with self._factory() as s:
            s.info.update(clinic_id=clinic_id, user_id=user_id, bypass_rls=bypass_rls)
            yield s

    async def dispose(self) -> None:
        await self.engine.dispose()
