from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Callable, Iterator, Literal, ParamSpec, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict


if __package__ == "backend.db":
    # The codebase normally runs with ``backend`` on sys.path. Support the
    # documented ``python -m backend.db.maintenance`` spelling as well.
    backend_root = str(Path(__file__).resolve().parents[1])
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)


logger = logging.getLogger(__name__)

MaintenanceTrigger = Literal["manual", "startup_idle"]
MaintenanceStatus = Literal["success", "skipped", "failed"]
BUSY_TIMEOUT_SECONDS = 5.0
DEFAULT_RECENT_LIMIT = 100
DEFAULT_SIZE_THRESHOLD_BYTES = 512 * 1024 * 1024
DEFAULT_FREELIST_THRESHOLD_BYTES = 64 * 1024 * 1024
DEFAULT_FREELIST_RATIO = 0.20

P = ParamSpec("P")
R = TypeVar("R")


class StorageMaintenanceResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: MaintenanceStatus
    trigger: MaintenanceTrigger
    started_at: datetime
    duration_ms: int
    size_before: int
    size_after: int
    reclaimed_bytes: int
    error_code: str | None = None


class StorageMaintenanceBusyError(RuntimeError):
    pass


class StorageMaintenanceCoordinator:
    """Process-local gate shared by storage writes and exclusive maintenance."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active_writes = 0
        self._maintenance_active = False

    @property
    def active_writes(self) -> int:
        with self._condition:
            return self._active_writes

    @contextmanager
    def write_request(self) -> Iterator[None]:
        with self._condition:
            while self._maintenance_active:
                self._condition.wait()
            self._active_writes += 1
        try:
            yield
        finally:
            with self._condition:
                self._active_writes -= 1
                self._condition.notify_all()

    @contextmanager
    def maintenance(self, timeout: float = BUSY_TIMEOUT_SECONDS) -> Iterator[None]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._maintenance_active or self._active_writes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise StorageMaintenanceBusyError("storage writes are active")
                self._condition.wait(timeout=remaining)
            self._maintenance_active = True
        try:
            yield
        finally:
            with self._condition:
                self._maintenance_active = False
                self._condition.notify_all()


storage_maintenance_coordinator = StorageMaintenanceCoordinator()


def coordinated_storage_write(func: Callable[P, R]) -> Callable[P, R]:
    @wraps(func)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        with storage_maintenance_coordinator.write_request():
            return func(*args, **kwargs)

    return wrapped


def init_storage_maintenance_db() -> None:
    from . import saves

    with saves._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS storage_maintenance_runs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK (status IN ('success', 'skipped', 'failed')),
                trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'startup_idle')),
                started_at TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                size_before INTEGER NOT NULL,
                size_after INTEGER NOT NULL,
                reclaimed_bytes INTEGER NOT NULL,
                error_code TEXT
            )
            """,
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_storage_maintenance_runs_started
            ON storage_maintenance_runs(started_at, id)
            """,
        )


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _database_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def storage_maintenance_needed() -> bool:
    from . import saves

    size = _database_size(saves.DB_PATH)
    if size >= _env_int(
        "STORAGE_MAINTENANCE_SIZE_THRESHOLD_BYTES",
        DEFAULT_SIZE_THRESHOLD_BYTES,
        minimum=1,
    ):
        return True
    if not saves.DB_PATH.exists():
        return False
    with saves._connect() as conn:
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
        freelist_count = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
    free_bytes = page_size * freelist_count
    free_ratio = freelist_count / page_count if page_count else 0.0
    return (
        free_bytes
        >= _env_int(
            "STORAGE_MAINTENANCE_FREELIST_THRESHOLD_BYTES",
            DEFAULT_FREELIST_THRESHOLD_BYTES,
            minimum=1,
        )
        and free_ratio
        >= _env_float(
            "STORAGE_MAINTENANCE_FREELIST_RATIO",
            DEFAULT_FREELIST_RATIO,
            minimum=0.0,
        )
    )


def _record_result(result: StorageMaintenanceResult) -> None:
    from . import saves

    with saves._connect() as conn:
        conn.execute(
            """
            INSERT INTO storage_maintenance_runs (
                id, status, trigger, started_at, duration_ms, size_before,
                size_after, reclaimed_bytes, error_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                result.status,
                result.trigger,
                result.started_at.isoformat(),
                result.duration_ms,
                result.size_before,
                result.size_after,
                result.reclaimed_bytes,
                result.error_code,
            ),
        )


def _result(
    *,
    status: MaintenanceStatus,
    trigger: MaintenanceTrigger,
    started_at: datetime,
    started_clock: float,
    size_before: int,
    size_after: int,
    error_code: str | None = None,
) -> StorageMaintenanceResult:
    return StorageMaintenanceResult(
        status=status,
        trigger=trigger,
        started_at=started_at,
        duration_ms=max(0, round((time.perf_counter() - started_clock) * 1000)),
        size_before=size_before,
        size_after=size_after,
        reclaimed_bytes=max(0, size_before - size_after),
        error_code=error_code,
    )


def _run_retention() -> None:
    from models.world import GameId
    from . import saves, worlds

    recent_limit = min(
        1000,
        _env_int("STORAGE_RETENTION_RECENT_LIMIT", DEFAULT_RECENT_LIMIT, minimum=1),
    )
    with saves._connect() as conn:
        game_ids = [row["id"] for row in conn.execute("SELECT id FROM games ORDER BY id")]
    for raw_game_id in game_ids:
        worlds.collect_retention(
            GameId(UUID(str(raw_game_id))),
            recent_limit=recent_limit,
            enabled=True,
        )


def _vacuum_database() -> None:
    from . import saves

    with saves._connect() as conn:
        conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_SECONDS * 1000)}")
        conn.execute("VACUUM")


def run_storage_maintenance(trigger: MaintenanceTrigger) -> StorageMaintenanceResult:
    if trigger not in {"manual", "startup_idle"}:
        raise ValueError("trigger must be 'manual' or 'startup_idle'")

    from . import saves

    started_at = datetime.now(timezone.utc)
    started_clock = time.perf_counter()
    saves.init_db()
    size_before = _database_size(saves.DB_PATH)

    try:
        _run_retention()
    except Exception:
        result = _result(
            status="failed",
            trigger=trigger,
            started_at=started_at,
            started_clock=started_clock,
            size_before=size_before,
            size_after=_database_size(saves.DB_PATH),
            error_code="retention_failed",
        )
        _record_result(result)
        return result

    try:
        with storage_maintenance_coordinator.maintenance():
            _vacuum_database()
    except StorageMaintenanceBusyError:
        status: MaintenanceStatus = "skipped"
        error_code = "active_writes"
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        status = "skipped" if "busy" in message or "locked" in message else "failed"
        error_code = "database_busy" if status == "skipped" else "vacuum_failed"
    except sqlite3.Error:
        status = "failed"
        error_code = "vacuum_failed"
    else:
        status = "success"
        error_code = None

    result = _result(
        status=status,
        trigger=trigger,
        started_at=started_at,
        started_clock=started_clock,
        size_before=size_before,
        size_after=_database_size(saves.DB_PATH),
        error_code=error_code,
    )
    _record_result(result)
    return result


_startup_attempt_scheduled = False


async def _run_startup_idle_maintenance() -> None:
    await asyncio.sleep(0)
    try:
        await asyncio.to_thread(run_storage_maintenance, "startup_idle")
    except Exception:
        logger.exception("startup storage maintenance failed")


def schedule_startup_idle_maintenance() -> asyncio.Task[None] | None:
    global _startup_attempt_scheduled
    if _startup_attempt_scheduled or not storage_maintenance_needed():
        return None
    _startup_attempt_scheduled = True
    return asyncio.create_task(_run_startup_idle_maintenance())


def _main() -> int:
    parser = argparse.ArgumentParser(description="Run controlled SQLite storage maintenance")
    parser.add_argument("--trigger", choices=("manual", "startup_idle"), default="manual")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    result = run_storage_maintenance(args.trigger)
    payload = result.model_dump(mode="json", exclude_none=True)
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"{result.status}: reclaimed {result.reclaimed_bytes} bytes "
            f"in {result.duration_ms} ms",
        )
    return 0 if result.status in {"success", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(_main())
