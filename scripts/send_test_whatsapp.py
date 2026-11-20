"""Dev helper: post one signed WhatsApp text to the local webhook for the demo clinic.

Usage: python scripts/send_test_whatsapp.py "+919825099088" "chest pain"
"""

import asyncio
import hashlib
import hmac
import json
import sys
import uuid
from pathlib import Path

import asyncpg
import httpx

env = dict(l.split("=", 1) for l in Path(".env").read_text(encoding="utf8").splitlines() if "=" in l and l[0] != "#")
secret = env["WHATSAPP_APP_SECRET"].split("#")[0].strip()
dsn = env["MIGRATION_DATABASE_URL"].split("#")[0].strip().replace("postgresql+psycopg://", "postgresql://")


async def demo_pnid() -> str:
    c = await asyncpg.connect(dsn)
    try:
        async with c.transaction():
            await c.execute("select set_config('app.bypass_rls','on',true)")
            return await c.fetchval(
                "select wa_phone_number_id from clinics where name = 'Smile Dental Studio' "
                "and wa_phone_number_id is not null order by updated_at desc limit 1"
            )
    finally:
        await c.close()


phone, text = sys.argv[1].lstrip("+"), sys.argv[2]
body = json.dumps({"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": asyncio.run(demo_pnid())},
    "messages": [{"from": phone, "id": f"wamid.dev.{uuid.uuid4().hex}", "type": "text", "text": {"body": text}}]}}]}]})
sig = "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
r = httpx.post("http://127.0.0.1:8000/api/v1/webhooks/whatsapp", content=body,
               headers={"x-hub-signature-256": sig, "content-type": "application/json"})
print(r.status_code)
