"""Launch the deterministic public-path lifecycle browser fixture.

This launcher is only selected by the explicit Playwright offline profile.  It
uses a temporary SQLite database and registers the test provider in the test
composition before importing the product app; production startup never imports
``tests.fakes`` or installs this provider.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import uvicorn


run_dir = Path(tempfile.mkdtemp(prefix="ming-lifecycle-e2e-")).resolve()
backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from db import saves  # noqa: E402

saves.DB_PATH = run_dir / "game.db"

# Explicit test composition only: no environment/provider setting is changed
# for product code and the fake is never registered by ``main``.
from ai.factory import _PROVIDERS  # noqa: E402
from ai.resilient import ResilientProvider  # noqa: E402
from api import state as api_state  # noqa: E402
from tests.fakes import FakeProvider  # noqa: E402

_PROVIDERS["fake"] = FakeProvider
api_state._set_runtime_provider_slot(
    ResilientProvider(FakeProvider(), timeout=1, retries=1),
)

from main import app  # noqa: E402


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
