from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from models.game import GameState

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


def save_game(state: GameState, name: str | None = None) -> int:
    if not name:
        name = f"崇祯{state.time.year}年{state.time.month}月-存档"
    game_time = f"崇祯{state.time.year}年{state.time.month}月"
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


def load_game(save_id: int) -> GameState:
    with _connect() as conn:
        row = conn.execute("SELECT state_json FROM saves WHERE id = ?", (save_id,)).fetchone()
    if row is None:
        raise SaveNotFoundError(save_id)
    try:
        return GameState.model_validate_json(row["state_json"])
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
    name = f"自动存档-崇祯{state.time.year}年{state.time.month}月"
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
