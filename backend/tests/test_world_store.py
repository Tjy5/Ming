from __future__ import annotations

import sqlite3

import pytest

from db import saves, worlds
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, MetricWorldDelta
from models.world import new_branch_id, new_client_action_id, new_delta_id


def _init_store(monkeypatch, tmp_path):
    db_path = tmp_path / "worlds.db"
    monkeypatch.setattr(saves, "DB_PATH", db_path)
    saves.init_db()
    return db_path


def _action(root, text: str = "赈济灾民") -> ActionIntent:
    return ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text=text,
        action_kind="decree",
    )


def _proposal(before: int, value: int, *, tier: str = "success") -> AdjudicationProposal:
    return AdjudicationProposal(
        result_tier=tier,
        key_factors=["地方请求赈济"],
        immediate_changes=["民心变化"],
        deltas=[
            MetricWorldDelta(
                delta_id=new_delta_id(),
                target_scope="world",
                field="civil_morale",
                operation="increment",
                before_value=before,
                value=value,
            ),
        ],
    )


def test_root_creation_round_trips_complete_state_and_initializes_all_tables(
    monkeypatch,
    tmp_path,
):
    db_path = _init_store(monkeypatch, tmp_path)
    state = create_initial_state()

    root = worlds.create_game_with_root(state)
    stored = worlds.load_version(root.version_id)
    head = worlds.get_branch_head(root.game_id, root.branch_id)

    assert head == root
    assert stored.ref == root
    assert stored.state.civil_morale == state.civil_morale
    assert stored.state.world_metadata.game_id == root.game_id
    assert stored.state.world_metadata.branch_id == root.branch_id
    assert stored.state.world_metadata.version_id == root.version_id

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'",
            ).fetchall()
        }
    with saves._connect() as conn:
        foreign_keys_enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert {
        "games",
        "branches",
        "versions",
        "settlements",
        "action_requests",
        "bookmarks",
        "terminal_records",
        "legacy_save_imports",
    } <= tables
    assert foreign_keys_enabled == 1


def test_graph_foreign_keys_reject_cross_game_and_cross_branch_heads(
    monkeypatch,
    tmp_path,
):
    _init_store(monkeypatch, tmp_path)
    first = worlds.create_game_with_root(create_initial_state())
    second = worlds.create_game_with_root(create_initial_state())

    with saves._connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE branches SET head_version_id = ? WHERE id = ?",
                (str(second.version_id), str(first.branch_id)),
            )

    sibling_branch_id = new_branch_id()
    with saves._connect() as conn:
        conn.execute(
            """
            INSERT INTO branches (id, game_id, created_at, status)
            VALUES (?, ?, ?, 'active')
            """,
            (
                str(sibling_branch_id),
                str(first.game_id),
                first.created_at.isoformat(),
            ),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE branches SET head_version_id = ? WHERE id = ?",
                (str(first.version_id), str(sibling_branch_id)),
            )


def test_settlement_version_head_and_action_request_roll_back_together(
    monkeypatch,
    tmp_path,
):
    _init_store(monkeypatch, tmp_path)
    initial = create_initial_state()
    root = worlds.create_game_with_root(initial)
    intent = _action(root)
    changed = initial.model_copy(deep=True)
    changed.civil_morale += 3

    def fail_version_insert(*args, **kwargs):
        raise sqlite3.OperationalError("injected version write failure")

    monkeypatch.setattr(worlds, "_insert_version", fail_version_insert)

    with pytest.raises(worlds.WorldStorageError) as exc_info:
        worlds.commit_settlement(
            intent,
            changed,
            _proposal(initial.civil_morale, 3),
        )

    assert exc_info.value.code == "world_storage_error"
    assert worlds.get_branch_head(root.game_id, root.branch_id) == root
    assert worlds.list_versions(root.game_id, root.branch_id) == [root]
    assert worlds.list_settlements(root.game_id, root.branch_id) == []
    assert worlds.get_action_request(
        root.game_id,
        root.branch_id,
        intent.client_action_id,
    ) is None


def test_failure_after_head_update_still_rolls_back_every_world_write(
    monkeypatch,
    tmp_path,
):
    _init_store(monkeypatch, tmp_path)
    initial = create_initial_state()
    root = worlds.create_game_with_root(initial)
    intent = _action(root, text="验证最终写入故障")
    changed = initial.model_copy(deep=True)
    changed.civil_morale += 1

    def fail_action_completion(*args, **kwargs):
        raise sqlite3.OperationalError("injected action completion failure")

    monkeypatch.setattr(worlds, "_complete_action_request", fail_action_completion)

    with pytest.raises(worlds.WorldStorageError):
        worlds.commit_settlement(
            intent,
            changed,
            _proposal(initial.civil_morale, 1),
        )

    assert worlds.get_branch_head(root.game_id, root.branch_id) == root
    assert worlds.list_versions(root.game_id, root.branch_id) == [root]
    assert worlds.list_settlements(root.game_id, root.branch_id) == []
    assert worlds.get_action_request(
        root.game_id,
        root.branch_id,
        intent.client_action_id,
    ) is None


def test_legal_failure_is_a_committed_settlement_not_a_system_error(
    monkeypatch,
    tmp_path,
):
    _init_store(monkeypatch, tmp_path)
    initial = create_initial_state()
    root = worlds.create_game_with_root(initial)
    changed = initial.model_copy(deep=True)
    changed.civil_morale -= 2

    result = worlds.commit_settlement(
        _action(root, text="尝试失败但形成后果"),
        changed,
        _proposal(initial.civil_morale, -2, tier="failure"),
    )

    assert result.facts.result_tier == "failure"
    assert worlds.get_branch_head(root.game_id, root.branch_id) == result.version
    assert worlds.load_version(result.version.version_id).state.civil_morale == changed.civil_morale
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1
