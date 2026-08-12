"""Launch an isolated backend for the operator release smoke.

The live key is supplied through the browser form.  This process deliberately
uses a temporary database, env file, and installation secret so an operator
run cannot mutate a developer checkout or inherit an effective provider.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import uvicorn


def _run_dir() -> Path:
    raw = os.environ.get("MING_SMOKE_RUN_DIR", "")
    if not raw:
        raise SystemExit("MING_SMOKE_RUN_DIR is required for release smoke")
    path = Path(raw).resolve()
    if path.parent != Path(tempfile.gettempdir()).resolve() or not path.name.startswith("ming-release-smoke-"):
        # The Node runner creates a narrowly scoped temp directory.  Refuse a
        # caller-provided checkout path rather than turning this into a product
        # configuration override.
        raise SystemExit("MING_SMOKE_RUN_DIR must be an isolated ming-release-smoke temp directory")
    path.mkdir(parents=True, exist_ok=True)
    return path


run_dir = _run_dir()

# When launched by Playwright with ``cwd=backend``, Python puts only the
# ``scripts`` directory on ``sys.path``.  Add the backend package root
# explicitly so the isolated launcher imports the same application modules as
# a normal ``python -m uvicorn main:app`` invocation.
backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

# Import only after the scratch location has been checked.  The DB modules use
# this shared path through ``db.saves._connect``.
from db import saves  # noqa: E402
from api import ai_settings_service  # noqa: E402
from api.ai_settings_service import AISettingsService  # noqa: E402

saves.DB_PATH = run_dir / "game.db"
ai_settings_service.set_ai_settings_service_for_testing(
    AISettingsService(
        environment=os.environ,
        env_path=run_dir / ".env",
        install_secret_path=run_dir / ".install-secret",
    ),
)

# The product provider factory still requires the user to complete settings
# test/apply.  No MING_LIVE_* value is interpreted as an effective provider.
if not os.environ.get("MING_RELEASE_CANDIDATE"):
    raise SystemExit("MING_RELEASE_CANDIDATE is required for release smoke")

from main import app  # noqa: E402


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
