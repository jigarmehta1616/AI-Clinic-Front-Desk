"""Grant (or revoke) platform-admin rights to a staff user by phone. Ops-only; audited.

Usage: python scripts/make_platform_admin.py +919000000009 [--revoke]
Uses MIGRATION_DATABASE_URL (schema owner) from .env; the user must have signed in at least once.
"""

import asyncio
import sys
import uuid
from pathlib import Path

import asyncpg

env = dict(l.split("=", 1) for l in Path(".env").read_text(encoding="utf8").splitlines() if "=" in l and l[0] != "#")
DSN = env["MIGRATION_DATABASE_URL"].split("#")[0].strip().replace("postgresql+psycopg://", "postgresql://")


async def main(phone: str, grant: bool) -> None:
    c = await asyncpg.connect(DSN)
    try:
        async with c.transaction():
            await c.execute("SELECT set_config('app.bypass_rls', 'on', true)")
            uid = await c.fetchval("UPDATE users SET is_platform_admin = $1 WHERE phone = $2 RETURNING id", grant, phone)
            if uid is None:
                raise SystemExit(f"no user with phone {phone} — they must sign in once first")
            await c.execute(
                "INSERT INTO audit_log (id, clinic_id, actor_type, actor_id, channel, action, entity_type, entity_id) "
                "VALUES ($1, NULL, 'system', NULL, 'system', $2, 'user', $3)",
                uuid.uuid4(), "platform.admin_granted" if grant else "platform.admin_revoked", str(uid),
            )
        print(f"{'granted' if grant else 'revoked'} platform admin for user {uid}; takes effect on next sign-in")
    finally:
        await c.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], "--revoke" not in sys.argv))
