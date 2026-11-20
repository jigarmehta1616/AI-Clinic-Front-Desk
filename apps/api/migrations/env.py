"""Alembic environment. Runs as the schema owner (MIGRATION_DATABASE_URL), synchronously via psycopg."""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # lets revisions `from rls import ...`

from alembic import context
from sqlalchemy import create_engine, pool

from clinicdesk.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)


def _url() -> str:
    url = config.attributes.get("url") or os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        env_file = Path(__file__).resolve().parents[3] / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf8").splitlines():
                if line.startswith("MIGRATION_DATABASE_URL="):
                    url = line.split("=", 1)[1].split("#", 1)[0].strip()
    if not url:
        raise RuntimeError("MIGRATION_DATABASE_URL is not set")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
