from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from engine.scripts import reload_script_registry
from models.positions import POSITION_REGISTRY


class DataManager:
    def __init__(
        self,
        *,
        ministers_path: Path | None = None,
        events_dir: Path | None = None,
    ) -> None:
        base_dir = Path(__file__).resolve().parents[1] / "data"
        self.ministers_path = ministers_path or (base_dir / "ministers.json")
        self.events_dir = events_dir or (base_dir / "events")

        self._lock = threading.RLock()
        self._ministers_cache: list[dict[str, Any]] | None = None
        self._ministers_mtime_ns: int = 0
        self._events_cache: dict[str, dict[str, Any]] | None = None
        self._events_signature: tuple[tuple[str, int, int], ...] | None = None

    # ── IO primitives ───────────────────────────────────

    @staticmethod
    def _atomic_write_bytes(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    @classmethod
    def _atomic_write_json(cls, path: Path, payload: Any) -> None:
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        cls._atomic_write_bytes(path, encoded)

    def _compute_events_signature(self) -> tuple[tuple[str, int, int], ...]:
        files = sorted(self.events_dir.glob("*.json"))
        signature: list[tuple[str, int, int]] = []
        for file in files:
            stat = file.stat()
            signature.append((file.name, stat.st_mtime_ns, stat.st_size))
        return tuple(signature)

    # ── Cache-backed readers ────────────────────────────

    def get_ministers(self) -> list[dict[str, Any]]:
        with self._lock:
            stat = self.ministers_path.stat()
            mtime_ns = stat.st_mtime_ns
            if self._ministers_cache is None or mtime_ns != self._ministers_mtime_ns:
                raw = json.loads(self.ministers_path.read_text(encoding="utf-8"))
                if not isinstance(raw, list):
                    raise ValueError("ministers.json must be a JSON array")
                self._ministers_cache = copy.deepcopy(raw)
                self._ministers_mtime_ns = mtime_ns
            return copy.deepcopy(self._ministers_cache)

    def get_events(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            signature = self._compute_events_signature()
            if self._events_cache is None or signature != self._events_signature:
                events: dict[str, dict[str, Any]] = {}
                for path in sorted(self.events_dir.glob("*.json")):
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError(f"{path} must be a JSON object")
                    script_id = payload.get("script_id")
                    if not isinstance(script_id, str) or not script_id.strip():
                        raise ValueError(f"{path} is missing a valid script_id")
                    script_id = script_id.strip()
                    if script_id in events:
                        raise ValueError(f"Duplicate script_id found in event files: {script_id}")
                    events[script_id] = copy.deepcopy(payload)
                self._events_cache = events
                self._events_signature = signature
            return copy.deepcopy(self._events_cache)

    def get_positions(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for name, info in POSITION_REGISTRY.items():
            result[name] = {
                "category": info.category.value,
                "weight": info.weight,
                "unique": info.unique,
                "aliases": list(info.aliases),
            }
        return result

    # ── Writers ─────────────────────────────────────────

    def write_ministers(self, ministers: list[dict[str, Any]]) -> None:
        if not isinstance(ministers, list):
            raise ValueError("ministers payload must be a list")
        with self._lock:
            self._atomic_write_json(self.ministers_path, ministers)
            self._ministers_cache = copy.deepcopy(ministers)
            self._ministers_mtime_ns = self.ministers_path.stat().st_mtime_ns

    def write_event(self, event_payload: dict[str, Any]) -> None:
        script_id = event_payload.get("script_id")
        if not isinstance(script_id, str) or not script_id.strip():
            raise ValueError("event payload must include a non-empty script_id")
        path = self.events_dir / f"{script_id.strip()}.json"
        with self._lock:
            self._atomic_write_json(path, event_payload)
            self._events_cache = None
            self._events_signature = None
        reload_script_registry(force=True)

    def delete_event(self, script_id: str) -> bool:
        path = self.events_dir / f"{script_id}.json"
        deleted = False
        with self._lock:
            if path.exists():
                path.unlink()
                deleted = True
                self._events_cache = None
                self._events_signature = None
        if deleted:
            reload_script_registry(force=True)
        return deleted

    def replace_events(self, events: list[dict[str, Any]]) -> None:
        with self._lock:
            existing_files = {p.name: p for p in self.events_dir.glob("*.json")}
            written_files: set[str] = set()
            for payload in events:
                script_id = payload.get("script_id")
                if not isinstance(script_id, str) or not script_id.strip():
                    raise ValueError("each event must include a non-empty script_id")
                filename = f"{script_id.strip()}.json"
                self._atomic_write_json(self.events_dir / filename, payload)
                written_files.add(filename)

            for filename, path in existing_files.items():
                if filename not in written_files:
                    path.unlink()

            self._events_cache = None
            self._events_signature = None
        reload_script_registry(force=True)

    # ── Backup helpers ──────────────────────────────────

    def export_bundle(self) -> dict[str, Any]:
        events = list(self.get_events().values())
        events.sort(key=lambda item: (item.get("trigger_year", 0), item.get("trigger_month", 0), item.get("script_id", "")))
        return {
            "ministers": self.get_ministers(),
            "events": events,
            "positions": self.get_positions(),
        }

    def import_bundle(
        self,
        *,
        ministers: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> None:
        with self._lock:
            old_ministers = self.ministers_path.read_bytes() if self.ministers_path.exists() else None
            old_events = {
                path.name: path.read_bytes()
                for path in self.events_dir.glob("*.json")
            }
            try:
                self._atomic_write_json(self.ministers_path, ministers)

                old_event_names = set(old_events.keys())
                new_event_names: set[str] = set()
                for payload in events:
                    script_id = payload.get("script_id")
                    if not isinstance(script_id, str) or not script_id.strip():
                        raise ValueError("each imported event must include a non-empty script_id")
                    name = f"{script_id.strip()}.json"
                    new_event_names.add(name)
                    self._atomic_write_json(self.events_dir / name, payload)

                for stale in old_event_names - new_event_names:
                    stale_path = self.events_dir / stale
                    if stale_path.exists():
                        stale_path.unlink()
            except Exception:
                if old_ministers is not None:
                    self._atomic_write_bytes(self.ministers_path, old_ministers)
                for path in self.events_dir.glob("*.json"):
                    if path.name not in old_events:
                        path.unlink()
                for filename, payload in old_events.items():
                    self._atomic_write_bytes(self.events_dir / filename, payload)
                self._ministers_cache = None
                self._events_cache = None
                self._events_signature = None
                raise

            self._ministers_cache = None
            self._events_cache = None
            self._events_signature = None

        reload_script_registry(force=True)


_DATA_MANAGER = DataManager()


def get_data_manager() -> DataManager:
    return _DATA_MANAGER

