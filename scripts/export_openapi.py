"""Write the API's OpenAPI schema to apps/web/openapi.json (input for `npm run gen:api`). No DB needed."""

import json
import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@localhost:1/unused")
os.environ.setdefault("JWT_SECRET", "x" * 40)
os.environ.setdefault("OTP_PEPPER", "y" * 40)

from clinicdesk.core.config import Settings  # noqa: E402
from clinicdesk.core.events import MemoryBroker  # noqa: E402
from clinicdesk.main import create_app  # noqa: E402

app = create_app(Settings(_env_file=None), broker=MemoryBroker())  # type: ignore[call-arg]
out = Path(__file__).resolve().parents[1] / "apps" / "web" / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=1, sort_keys=True) + "\n", encoding="utf8")
print(f"wrote {out} ({len(app.openapi()['paths'])} paths)")
