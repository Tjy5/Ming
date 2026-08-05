from __future__ import annotations

import math
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from models.game import (
    GameState,
    get_initial_ministers,
    normalize_decree_category_usage,
)

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
    {"name": "天历", "start_year": 1328},
    {"name": "至顺", "start_year": 1330},
    {"name": "元统", "start_year": 1333},
    {"name": "至元", "start_year": 1335},
    {"name": "至正", "start_year": 1341},
    {"name": "洪武", "start_year": 1368},
]

_DISASTER_BY_THREAT = {"none": 0, "元军": 40, "汉军": 45, "吴军": 40, "民变": 60, "土司": 30, "海盗": 20}
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
    initial_ministers = get_initial_ministers()

    # ── time migration ──
    t = data.setdefault("time", {})
    year = t.get("year")
    if isinstance(year, int) and year < 100:
        year = year + 1356
        t["year"] = year

    if "era_name" not in t or "era_year" not in t:
        y = year if isinstance(year, int) else 1356
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

    # ── resource migration ──
    treasury_raw = data.pop("treasury", None)
    treasury_legacy = max(0, math.floor(treasury_raw)) if isinstance(treasury_raw, (int, float)) else None

    resource_migrated = False
    if "national_treasury" not in data:
        if treasury_legacy is not None:
            data["national_treasury"] = math.floor(treasury_legacy * 0.5)
            resource_migrated = True
        else:
            data["national_treasury"] = 20
    if "imperial_treasury" not in data:
        if treasury_legacy is not None:
            data["imperial_treasury"] = math.floor(treasury_legacy * 0.3)
            resource_migrated = True
        else:
            data["imperial_treasury"] = 10
    if "grain" not in data:
        if treasury_legacy is not None:
            data["grain"] = math.floor(treasury_legacy * 0.2)
            resource_migrated = True
        else:
            data["grain"] = 500
    if resource_migrated:
        notes.append("迁移了旧国库至国库/内帑/粮储")

    military_raw = data.pop("military_supply", None)
    if "military_strength" not in data:
        if isinstance(military_raw, (int, float)):
            data["military_strength"] = max(0, math.floor(military_raw))
            notes.append("迁移了旧军备至军力")
        else:
            data["military_strength"] = 40

    population_raw = data.get("population")
    if isinstance(population_raw, (int, float)) and population_raw < 1000:
        data["population"] = max(0, math.floor(population_raw)) * 150
        notes.append("按万人口口径调整了人口数据")

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
        data["ministers"] = [m.model_dump() for m in initial_ministers]
        notes.append("补充了大臣数据")
    elif not _valid_ministers(ministers_raw):
        data["ministers"] = [m.model_dump() for m in initial_ministers]
        notes.append("重置了损坏的大臣数据")
    else:
        loyalty_migrated = False
        for minister in data["ministers"]:
            if "loyalty" not in minister:
                minister["loyalty"] = 50
                loyalty_migrated = True
        if loyalty_migrated:
            notes.append("补充了大臣忠诚度数据")

        init_map = {m.name: m for m in initial_ministers}

        if len(data["ministers"]) < 50:
            t_data = data.get("time", {})
            raw_year = t_data.get("year", 1356)
            raw_month = t_data.get("month", 3)
            try:
                curr_key = int(raw_year) * 12 + int(raw_month)
            except (TypeError, ValueError):
                curr_key = 1356 * 12 + 3

            existing = []
            existing_names: set[str] = set()
            for old_m in data["ministers"]:
                name = old_m.get("name")
                existing_names.add(name)
                if name in init_map:
                    im = init_map[name]
                    old_m.setdefault("position", "、".join(im.positions))
                    old_m.setdefault("entry_year", im.entry_year)
                    old_m.setdefault("entry_month", im.entry_month)
                    old_m.setdefault("historical_note", im.historical_note)
                else:
                    old_m.setdefault("position", "")
                    old_m.setdefault("entry_year", 1356)
                    old_m.setdefault("entry_month", 3)
                    old_m.setdefault("historical_note", "")
                existing.append(old_m)

            for im in initial_ministers:
                if im.name not in existing_names:
                    nm = im.model_dump()
                    nm["loyalty"] = 50
                    entry_key = im.entry_year * 12 + im.entry_month
                    if entry_key > curr_key:
                        nm["status"] = "not_yet_entered"
                    existing.append(nm)

            data["ministers"] = existing
            notes.append("已扩充大臣至100+人")
        else:
            fields_patched = False
            for m in data["ministers"]:
                needs_patch = any(
                    k not in m for k in ("positions", "entry_year", "entry_month", "historical_note")
                )
                if needs_patch:
                    fields_patched = True
                    im = init_map.get(m.get("name"))
                    # Migrate position -> positions
                    if "position" in m and "positions" not in m:
                        m["positions"] = [m.pop("position")] if m["position"] else []
                    m.setdefault("positions", im.positions if im else [])
                    m.setdefault("entry_year", im.entry_year if im else 1356)
                    m.setdefault("entry_month", im.entry_month if im else 3)
                    m.setdefault("historical_note", im.historical_note if im else "")
                    m.setdefault("is_eunuch", im.is_eunuch if im else False)
            if fields_patched:
                notes.append("补全了大臣生平属性")

    # ── phase field (阶段A预留) ──
    if "phase" not in data:
        data["phase"] = "governance"
        notes.append("补充了阶段字段")

    # ── resolved_script_ids ──
    if "resolved_script_ids" not in data:
        data["resolved_script_ids"] = []

    # ── decrees_this_month migration (decree-type -> category-keyed) ──
    if "decrees_this_month" not in data:
        data["decrees_this_month"] = {}
    else:
        raw_usage = data.get("decrees_this_month")
        normalized_usage = normalize_decree_category_usage(raw_usage)
        if raw_usage != normalized_usage:
            notes.append("迁移了政令月度限制为类别键")
        data["decrees_this_month"] = normalized_usage

    # ── trigger decisions ──
    if "trigger_decisions" not in data or not isinstance(data.get("trigger_decisions"), dict):
        data["trigger_decisions"] = {}

    # ── phase3 fields migration ──
    if "memorials" not in data:
        data["memorials"] = []
    if "memorial_cooldowns" not in data:
        data["memorial_cooldowns"] = {}
    if "last_assembly" not in data:
        data["last_assembly"] = None
    if "loyalty_zero_triggered" not in data:
        data["loyalty_zero_triggered"] = []
    if "last_assembly_month" not in data:
        data["last_assembly_month"] = 0
    if "consecutive_waits" not in data:
        data["consecutive_waits"] = 0
    if "minister_conversations" not in data:
        data["minister_conversations"] = {}

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
