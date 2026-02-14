from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from models.game import GameState, INITIAL_MINISTERS

DB_PATH = Path(__file__).parent.parent / "game_saves.db"
MAX_SAVES = 20


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS saves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                game_time TEXT NOT NULL,
                created_at TEXT NOT NULL,
                state_json TEXT NOT NULL
            )
        """)


def _era_display(state: GameState) -> str:
    t = state.time
    year_str = "元年" if t.era_year == 1 else f"{t.era_year}年"
    return f"{t.era_name}{year_str}{t.month}月"


def save_game(state: GameState, name: str | None = None) -> int:
    display = _era_display(state)
    if not name:
        name = f"{display}-存档"
    game_time = display
    created_at = datetime.now(timezone.utc).isoformat()
    state_json = state.model_dump_json()
    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO saves (name, game_time, created_at, state_json) VALUES (?, ?, ?, ?)",
                (name, game_time, created_at, state_json),
            )
            return cur.lastrowid  # type: ignore[return-value]
    except sqlite3.Error:
        raise StorageError("storage_error", "存档失败，存储异常")


_ERA_CONFIG = [
    {"name": "天启", "start_year": 1621},
    {"name": "崇祯", "start_year": 1628},
]

_DISASTER_BY_THREAT = {"none": 0, "后金": 40, "民变": 60, "土司": 30, "海盗": 20}
_TAX_RATE_BY_CONTRIB = {"low": 0.3, "medium": 0.5, "high": 0.8}



def _valid_ministers(raw: object) -> bool:
    if not isinstance(raw, list) or not raw:
        return False
    return all(
        isinstance(m, dict)
        and isinstance(m.get("name"), str)
        and isinstance(m.get("faction"), str)
        for m in raw
    )


def _migrate_save(data: dict) -> list[str]:
    notes: list[str] = []

    # ── time migration ──
    t = data.setdefault("time", {})
    year = t.get("year")
    if isinstance(year, int) and year < 100:
        year = year + 1627
        t["year"] = year

    if "era_name" not in t or "era_year" not in t:
        y = year if isinstance(year, int) else 1627
        if "year" not in t:
            t["year"] = y
        era = _ERA_CONFIG[0]
        for e in _ERA_CONFIG:
            if e["start_year"] <= y:
                era = e
            else:
                break
        t.setdefault("era_name", era["name"])
        t.setdefault("era_year", y - era["start_year"] + 1)
        notes.append("补充了年号信息")

    # ── region migration ──
    region_migrated = False
    for r in data.get("regions", []):
        stab = r.get("stability", 50)
        threat = r.get("threat", "none")
        contrib = r.get("tax_contribution", "medium")

        if "civil_morale" not in r:
            r["civil_morale"] = max(0, min(100, stab - 5))
            region_migrated = True
        if "rebellion_risk" not in r:
            r["rebellion_risk"] = 10 if threat == "none" else max(0, min(100, 100 - stab))
            region_migrated = True
        if "tax_rate" not in r:
            r["tax_rate"] = _TAX_RATE_BY_CONTRIB.get(contrib, 0.5)
            region_migrated = True
        if "tax_collected" not in r:
            r["tax_collected"] = 0
            region_migrated = True
        if "disaster_level" not in r:
            r["disaster_level"] = _DISASTER_BY_THREAT.get(threat, 0)
            region_migrated = True
    if region_migrated:
        notes.append("补充了分省详细数据")

    # ── minister migration ──
    ministers_raw = data.get("ministers")
    if "ministers" not in data:
        data["ministers"] = [m.model_dump() for m in INITIAL_MINISTERS]
        notes.append("补充了大臣数据")
    elif not _valid_ministers(ministers_raw):
        data["ministers"] = [m.model_dump() for m in INITIAL_MINISTERS]
        notes.append("重置了损坏的大臣数据")

    # ── resolved_script_ids ──
    if "resolved_script_ids" not in data:
        data["resolved_script_ids"] = []

    return notes


def load_game(save_id: int) -> tuple[GameState, bool, str]:
    with _connect() as conn:
        row = conn.execute("SELECT state_json FROM saves WHERE id = ?", (save_id,)).fetchone()
    if row is None:
        raise SaveNotFoundError(save_id)
    try:
        data = json.loads(row["state_json"])
        notes = _migrate_save(data)
        state = GameState.model_validate(data)
        migrated = bool(notes)
        note = f"旧存档已自动迁移：{'；'.join(notes)}" if notes else ""
        return state, migrated, note
    except (SaveNotFoundError, CorruptSaveError):
        raise
    except Exception:
        raise CorruptSaveError(save_id)


def list_saves() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, game_time, created_at FROM saves ORDER BY created_at DESC LIMIT ?",
            (MAX_SAVES,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_save(save_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM saves WHERE id = ?", (save_id,))
        if cur.rowcount == 0:
            raise SaveNotFoundError(save_id)
        return True


def auto_save(state: GameState) -> None:
    name = f"自动存档-{_era_display(state)}"
    try:
        save_game(state, name)
    except Exception:
        pass  # auto-save failure must not block gameplay


# ── Exceptions ──────────────────────────────────────────

class SaveNotFoundError(Exception):
    def __init__(self, save_id: int):
        self.save_id = save_id
        super().__init__(f"Save {save_id} not found")


class CorruptSaveError(Exception):
    def __init__(self, save_id: int):
        self.save_id = save_id
        super().__init__(f"Save {save_id} is corrupt")


class StorageError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)
