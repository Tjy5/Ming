"""Smoke check: verify backend import contract and documented startup paths.

These tests validate that the documented local startup commands actually work:
  Primary:   cd backend && python -m uvicorn main:app --reload --port 8000
  Alternate: PYTHONPATH=backend uvicorn backend.main:app --reload --port 8000  (from repo root)

They do NOT start a long-running server; they only check imports and route wiring.
"""

import sys
import subprocess
import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


def routes_in(app):
    return {route.path for route in app.routes if hasattr(route, "path")}


class TestPrimaryStartupImportContract:
    """Simulate the primary documented startup: working directory is backend/."""

    def test_main_imports_without_error(self):
        """All top-level imports in main.py resolve when cwd is backend/."""
        sys.path.insert(0, str(BACKEND_DIR))
        try:
            from main import app  # noqa: F811
        finally:
            sys.path.pop(0)

    def test_top_level_api_packages_import(self):
        """Packages used as `from api.routes import router` resolve."""
        sys.path.insert(0, str(BACKEND_DIR))
        try:
            import api.routes  # noqa: F401
            import api.save_routes  # noqa: F401
            import api.settings_routes  # noqa: F401
            import api.assembly_routes  # noqa: F401
            import api.admin_routes  # noqa: F401
            import api.chat_routes  # noqa: F401
            import api.state  # noqa: F401
        finally:
            sys.path.pop(0)


class TestFastAPIAppRoutes:
    """Verify expected routes are wired in the FastAPI app."""

    def test_app_has_health_route(self):
        sys.path.insert(0, str(BACKEND_DIR))
        try:
            from main import app
            route_paths = routes_in(app)
            assert "/api/health" in route_paths
        finally:
            sys.path.pop(0)

    def test_app_has_openapi_schema_endpoint(self):
        """FastAPI auto-generates /openapi.json when app is created."""
        sys.path.insert(0, str(BACKEND_DIR))
        try:
            from main import app
            schema = app.openapi()
            assert "info" in schema
            assert schema["info"]["title"] == "元末纪事"
        finally:
            sys.path.pop(0)

    def test_app_has_admin_verify_route(self):
        sys.path.insert(0, str(BACKEND_DIR))
        try:
            from main import app
            route_paths = routes_in(app)
            assert "/api/admin/verify" in route_paths
        finally:
            sys.path.pop(0)


class TestSubprocessStartupSmoke:
    """Verify the exact documented startup command can at least import without error."""

    def test_cd_backend_minus_m_uvicorn_main_import(self):
        """`cd backend && python -c "import main"` should succeed (no server)."""
        result = subprocess.run(
            [sys.executable, "-c", "import main"],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_root_pythonpath_backend_import_backend_dot_main(self):
        """`PYTHONPATH=backend python -c "import backend.main"` from repo root."""
        env = os.environ.copy()
        env["PYTHONPATH"] = "backend"
        result = subprocess.run(
            [sys.executable, "-c", "import backend.main"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
