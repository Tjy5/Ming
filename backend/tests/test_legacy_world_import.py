from __future__ import annotations

import sqlite3

import pytest

from db import saves, worlds
from models.game import create_initial_state


def _legacy_save(monkeypatch, tmp_path):
    db_path = tmp_path / "legacy-import.db"
    monkeypatch.setattr(saves, "DB_PATH", db_path)
    saves.init_db()
    source_state = create_initial_state()
    save_id = saves.save_game(source_state, "只读旧存档")
    with saves._connect() as conn:
        row = conn.execute(
            "SELECT name, game_time, created_at, state_json FROM saves WHERE id = ?",
            (save_id,),
        ).fetchone()
    assert row is not None
    return db_path, save_id, dict(row), source_state


def test_legacy_import_is_idempotent_protected_and_does_not_rewrite_source(
    monkeypatch,
    tmp_path,
):
    db_path, save_id, before_row, source_state = _legacy_save(monkeypatch, tmp_path)

    first = worlds.import_legacy_save(save_id)
    replay = worlds.import_legacy_save(save_id)

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.version == first.version
    assert replay.state == first.state
    assert first.version.protected is True
    assert first.state.world_metadata.source_kind == "legacy_save"
    assert first.state.world_metadata.schema_version == 1
    assert first.state.player_world_status.player_character_id is not None
    assert len(first.state.entity_registry) >= (
        len(source_state.ministers) + len(source_state.factions) + len(source_state.regions)
    )
    assert all(
        entity.origin_version_id == first.version.version_id
        and entity.source.kind == "legacy_save"
        and entity.source.reference == str(save_id)
        for entity in first.state.entity_registry.values()
    )

    with saves._connect() as conn:
        after_row = conn.execute(
            "SELECT name, game_time, created_at, state_json FROM saves WHERE id = ?",
            (save_id,),
        ).fetchone()
        ledger = conn.execute(
            "SELECT source_state_bytes FROM legacy_save_imports WHERE save_id = ?",
            (save_id,),
        ).fetchone()
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("games", "branches", "versions", "legacy_save_imports")
        }

    assert after_row is not None and dict(after_row) == before_row
    assert ledger is not None
    assert bytes(ledger["source_state_bytes"]) == before_row["state_json"].encode("utf-8")
    assert counts == {"games": 1, "branches": 1, "versions": 1, "legacy_save_imports": 1}
    assert db_path.exists()


def test_legacy_import_failure_rolls_back_new_graph_and_keeps_source(
    monkeypatch,
    tmp_path,
):
    _, save_id, before_row, _ = _legacy_save(monkeypatch, tmp_path)

    def fail_ledger_insert(*args, **kwargs):
        raise sqlite3.OperationalError("injected ledger failure")

    monkeypatch.setattr(worlds, "_insert_legacy_import", fail_ledger_insert)

    with pytest.raises(worlds.WorldStorageError):
        worlds.import_legacy_save(save_id)

    with saves._connect() as conn:
        after_row = conn.execute(
            "SELECT name, game_time, created_at, state_json FROM saves WHERE id = ?",
            (save_id,),
        ).fetchone()
        graph_counts = [
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("games", "branches", "versions", "legacy_save_imports")
        ]

    assert after_row is not None and dict(after_row) == before_row
    assert graph_counts == [0, 0, 0, 0]
