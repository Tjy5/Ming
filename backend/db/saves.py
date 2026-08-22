from __future__ import annotations

import math
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from models.game import (
    GameState,
    get_initial_ministers,
    normalize_decree_category_usage,
    normalize_history_payload,
)
from .maintenance import coordinated_storage_write

DB_PATH = Path(
    os.getenv("MING_GAME_SAVES_DB_PATH", Path(__file__).parent.parent / "game_saves.db"),
)
MAX_SAVES = 20

# 版本化世界时钟允许开放沙盒越过历史朝代边界。这里只保留历元下限；
# 旧崇祯剧本通过明确的年号身份识别，而不是把 1368 当作时间上限。
COMPATIBLE_YEAR_MIN = 1328
INCOMPATIBLE_LEGACY_ERA_NAMES = frozenset({"崇祯"})


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
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
    # Keep all local SQLite schema initialization behind the existing startup
    # hook while the assessment repository remains a separate data owner.
    from .ai_assessments import init_ai_assessments
    from .worlds import init_worlds_db
    from .narrative_memory import init_narrative_memory_db
    from .maintenance import init_storage_maintenance_db

    init_ai_assessments()
    init_worlds_db()
    init_narrative_memory_db()
    init_storage_maintenance_db()


def _era_display(state: GameState) -> str:
    t = state.time
    year_str = "元年" if t.era_year == 1 else f"{t.era_year}年"
    return f"{t.era_name}{year_str}{t.month}月"


@coordinated_storage_write
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
    from engine.calendar import (
        clock_and_projection_from_calendar,
        projection_from_absolute_hour,
        resolve_era,
    )
    from models.world import WorldClock

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
        era_name, era_year = resolve_era(y)
        t.setdefault("era_name", era_name)
        t.setdefault("era_year", era_year)
        notes.append("补充了年号信息")

    # The source row remains untouched; this decoded copy receives the stable
    # V1 clock identity and a deterministic first-day/first-hour legacy anchor.
    clock_raw = t.get("clock")
    calendar_raw = t.get("calendar")
    if not isinstance(clock_raw, dict):
        month = t.get("month", 1)
        if (
            year == 1328
            and isinstance(month, int)
            and month < 10
        ):
            month = 10
            t["month"] = month
            notes.append("将早于世界历元的旧时间钳制到历元")
        if (
            isinstance(year, int)
            and year >= 1328
            and isinstance(month, int)
            and 1 <= month <= 12
        ):
            clock, calendar = clock_and_projection_from_calendar(year=year, month=month)
            t["clock"] = clock.model_dump(mode="json")
            t["calendar"] = calendar.model_dump(mode="json")
            t["time_migration_source"] = "legacy_year_month"
            notes.append("补充了版本化世界时钟")
    elif not isinstance(calendar_raw, dict):
        clock = WorldClock.model_validate(clock_raw)
        calendar = projection_from_absolute_hour(
            clock.absolute_hour,
            calendar_version=clock.calendar_version,
        )
        t["calendar"] = calendar.model_dump(mode="json")
        notes.append("补充了历法投影视图")

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

    history, history_migrated = normalize_history_payload(data.get("history_log"))
    data["history_log"] = history
    if history_migrated:
        notes.append("迁移了历史记录序号、类别与政区元数据")

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

    # ── 跑团字段回填（阶段B，静默无 note：模型默认值语义，非 gameplay 迁移）──
    if "chapter" not in data:
        data["chapter"] = "childhood"
    if "chapter_turns" not in data:
        data["chapter_turns"] = 0
    if "character_sheets" not in data:
        data["character_sheets"] = {}
    if "growth_log" not in data:
        data["growth_log"] = []

    return notes


def _incompatible_year(data: dict) -> bool:
    """检测历元前档案或明确属于旧崇祯剧本的档案。"""
    t = data.get("time")
    if not isinstance(t, dict):
        return False
    year = t.get("year")
    if isinstance(year, int) and year < COMPATIBLE_YEAR_MIN:
        return True
    era_name = t.get("era_name")
    return isinstance(era_name, str) and era_name.strip() in INCOMPATIBLE_LEGACY_ERA_NAMES


def load_game(save_id: int) -> tuple[GameState, bool, str]:
    with _connect() as conn:
        row = conn.execute("SELECT state_json FROM saves WHERE id = ?", (save_id,)).fetchone()
    if row is None:
        raise SaveNotFoundError(save_id)
    try:
        data = json.loads(row["state_json"])
        notes = _migrate_save(data)
        if _incompatible_year(data):
            raise IncompatibleSaveError(save_id)
        state = GameState.model_validate(data)
        migrated = bool(notes)
        note = f"旧存档已自动迁移：{'；'.join(notes)}" if notes else ""
        return state, migrated, note
    except (SaveNotFoundError, CorruptSaveError, IncompatibleSaveError):
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


@coordinated_storage_write
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


class IncompatibleSaveError(Exception):
    """旧剧本存档（如崇祯朝）与元末明初剧本不兼容。"""

    def __init__(self, save_id: int):
        self.save_id = save_id
        super().__init__(f"Save {save_id} is incompatible with the current scenario")


class StorageError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)
