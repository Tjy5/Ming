from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from db import maintenance, saves, worlds
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, MetricWorldDelta
from models.world import new_client_action_id, new_delta_id


def _setup(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "maintenance.db"
    monkeypatch.setattr(saves, "DB_PATH", path)
    saves.init_db()
    return path


def _save_slot_record(save_id: int) -> dict:
    with saves._connect() as conn:
        row = conn.execute(
            "SELECT id, name, game_time, created_at, state_json FROM saves WHERE id = ?",
            (save_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def _commit(parent, state, text: str):
    intent = ActionIntent(
        game_id=parent.game_id,
        branch_id=parent.branch_id,
        expected_parent_version_id=parent.version_id,
        client_action_id=new_client_action_id(),
        raw_text=text,
        action_kind="decree",
    )
    changed = state.model_copy(deep=True)
    changed.civil_morale += 1
    result = worlds.commit_settlement(
        intent,
        changed,
        AdjudicationProposal(
            result_tier="success",
            key_factors=["maintenance fixture"],
            immediate_changes=["morale"],
            deltas=[
                MetricWorldDelta(
                    delta_id=new_delta_id(),
                    target_scope="world",
                    field="civil_morale",
                    operation="increment",
                    before_value=state.civil_morale,
                    value=1,
                ),
            ],
        ),
    )
    return result.version, worlds.load_version(result.version.version_id).state


def test_manual_maintenance_vacuums_and_audits(monkeypatch, tmp_path):
    path = _setup(monkeypatch, tmp_path)

    result = maintenance.run_storage_maintenance("manual")

    assert result.status == "success"
    assert result.trigger == "manual"
    assert result.size_after == path.stat().st_size
    assert result.reclaimed_bytes == max(0, result.size_before - result.size_after)
    with saves._connect() as conn:
        audit = conn.execute("SELECT * FROM storage_maintenance_runs").fetchone()
    assert audit is not None
    assert audit["status"] == "success"
    assert audit["trigger"] == "manual"


def test_busy_maintenance_is_skipped_and_audited(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    slot_state = create_initial_state()
    slot_id = saves.save_game(slot_state, "busy maintenance slot")
    slot_before = _save_slot_record(slot_id)

    @contextmanager
    def busy_gate(*_args, **_kwargs):
        raise maintenance.StorageMaintenanceBusyError("injected active write")
        yield

    monkeypatch.setattr(maintenance.storage_maintenance_coordinator, "maintenance", busy_gate)
    result = maintenance.run_storage_maintenance("manual")

    assert result.status == "skipped"
    assert result.error_code == "active_writes"
    with saves._connect() as conn:
        audit = conn.execute("SELECT status, error_code FROM storage_maintenance_runs").fetchone()
    assert tuple(audit) == ("skipped", "active_writes")
    assert _save_slot_record(slot_id) == slot_before
    loaded, _migrated, _notes = saves.load_game(slot_id)
    assert loaded.model_dump() == slot_state.model_dump()
    assert saves.save_game(loaded, "after skipped maintenance") > slot_id


def test_vacuum_failure_preserves_committed_retention_and_service(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("STORAGE_RETENTION_RECENT_LIMIT", "1")
    slot_state = create_initial_state()
    slot_id = saves.save_game(slot_state, "failed maintenance slot")
    slot_before = _save_slot_record(slot_id)
    root = worlds.create_game_with_root(create_initial_state())
    first, state = _commit(root, worlds.load_version(root.version_id).state, "first")
    second, state = _commit(first, state, "second")
    third, state = _commit(second, state, "third")

    def fail_vacuum():
        raise sqlite3.OperationalError("injected vacuum failure")

    monkeypatch.setattr(maintenance, "_vacuum_database", fail_vacuum)
    result = maintenance.run_storage_maintenance("manual")

    assert result.status == "failed"
    assert result.error_code == "vacuum_failed"
    assert str(first.version_id) not in {
        str(ref.version_id) for ref in worlds.list_versions(root.game_id, root.branch_id)
    }
    fourth, _ = _commit(third, state, "after failed vacuum")
    assert worlds.get_branch_head(root.game_id, root.branch_id).version_id == fourth.version_id
    assert _save_slot_record(slot_id) == slot_before
    loaded, _migrated, _notes = saves.load_game(slot_id)
    assert loaded.model_dump() == slot_state.model_dump()
    assert saves.save_game(loaded, "after failed maintenance") > slot_id


def test_module_cli_emits_json_against_explicit_temporary_database(tmp_path):
    db_path = tmp_path / "cli-maintenance.db"
    project_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.db.maintenance",
            "--trigger",
            "manual",
            "--json",
        ],
        cwd=project_root,
        env={**__import__("os").environ, "MING_GAME_SAVES_DB_PATH": str(db_path)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "success"
    assert payload["trigger"] == "manual"
    assert db_path.exists()


def test_world_save_and_retention_writes_share_one_coordinator(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    entries: list[int] = []

    @contextmanager
    def observed_write_gate():
        entries.append(1)
        yield

    monkeypatch.setattr(
        maintenance.storage_maintenance_coordinator,
        "write_request",
        observed_write_gate,
    )
    state = create_initial_state()
    root = worlds.create_game_with_root(state)
    saves.save_game(state, "coordinated")
    worlds.collect_retention(root.game_id, enabled=True)

    assert entries == [1, 1, 1]


@pytest.mark.asyncio
async def test_startup_idle_maintenance_is_scheduled_once(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(maintenance, "_startup_attempt_scheduled", False)
    monkeypatch.setattr(maintenance, "storage_maintenance_needed", lambda: True)
    monkeypatch.setattr(
        maintenance,
        "run_storage_maintenance",
        lambda trigger: calls.append(trigger),
    )

    task = maintenance.schedule_startup_idle_maintenance()
    duplicate = maintenance.schedule_startup_idle_maintenance()
    assert task is not None
    assert duplicate is None
    await task

    assert calls == ["startup_idle"]
