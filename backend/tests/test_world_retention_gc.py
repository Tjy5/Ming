from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest

from db import saves, worlds
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, MetricWorldDelta
from models.world import new_client_action_id, new_delta_id


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "retention-gc.db")
    saves.init_db()


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
    proposal = AdjudicationProposal(
        result_tier="success",
        key_factors=["retention fixture"],
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
    )
    result = worlds.commit_settlement(intent, changed, proposal)
    return result.version, worlds.load_version(result.version.version_id).state


def test_disabled_collection_is_report_only(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    root = worlds.create_game_with_root(create_initial_state())
    plan = worlds.collect_retention(root.game_id, root.branch_id, recent_limit=1)

    assert plan.enabled is False
    assert plan.committed is False
    assert worlds.list_versions(root.game_id, root.branch_id) == [root]
    with saves._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM retention_gc_audits").fetchone()[0] == 0


def test_enabled_collection_deletes_only_unreferenced_versions_and_audits(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    root = worlds.create_game_with_root(create_initial_state())
    first, state = _commit(root, worlds.load_version(root.version_id).state, "first")
    second, state = _commit(first, state, "second")
    third, _ = _commit(second, state, "third")

    result = worlds.collect_retention(
        root.game_id,
        root.branch_id,
        recent_limit=1,
        enabled=True,
    )

    assert result.committed is True
    assert str(first.version_id) in result.deleted_version_ids
    assert str(second.version_id) not in result.deleted_version_ids  # monthly recovery
    assert str(third.version_id) not in result.deleted_version_ids  # branch head
    assert worlds.get_branch_head(root.game_id, root.branch_id).version_id == third.version_id
    with saves._connect() as conn:
        audit = conn.execute(
            "SELECT deleted_version_ids_json, committed FROM retention_gc_audits WHERE id = ?",
            (result.audit_id,),
        ).fetchone()
    assert audit is not None
    assert audit["committed"] == 1
    assert str(first.version_id) in audit["deleted_version_ids_json"]
    detached = worlds.load_version(second.version_id)
    assert detached.ref.parent_version_id is None
    assert detached.state.civil_morale == state.civil_morale
    saves.init_db()
    assert worlds.load_version(second.version_id).state == detached.state


def test_collection_detaches_long_candidate_chain_before_uuid_ordered_deletes(
    monkeypatch,
    tmp_path,
):
    _setup(monkeypatch, tmp_path)
    root = worlds.create_game_with_root(create_initial_state())
    parent = root
    state = worlds.load_version(root.version_id).state
    for index in range(12):
        parent, state = _commit(parent, state, f"chain-{index}")

    result = worlds.collect_retention(
        root.game_id,
        root.branch_id,
        recent_limit=1,
        enabled=True,
    )

    assert result.committed is True
    assert result.deleted_version_ids
    assert worlds.load_version(parent.version_id).state == state


def test_retention_recent_limit_is_strictly_bounded(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    root = worlds.create_game_with_root(create_initial_state())

    for invalid in (True, 0, 1001, 1.5):
        with pytest.raises(ValueError, match="1 to 1000"):
            worlds.plan_retention(root.game_id, recent_limit=invalid)


def test_retention_audit_failure_rolls_back_detaches_and_deletes(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    root = worlds.create_game_with_root(create_initial_state())
    first, state = _commit(root, worlds.load_version(root.version_id).state, "first")
    second, state = _commit(first, state, "second")
    third, _ = _commit(second, state, "third")
    with saves._connect() as conn:
        conn.execute(
            """
            CREATE TRIGGER fail_retention_audit
            BEFORE INSERT ON retention_gc_audits
            BEGIN
                SELECT RAISE(ABORT, 'injected audit failure');
            END
            """,
        )

    with pytest.raises(worlds.WorldStorageError):
        worlds.collect_retention(
            root.game_id,
            root.branch_id,
            recent_limit=1,
            enabled=True,
        )

    assert worlds.load_version(first.version_id).ref.parent_version_id == root.version_id
    assert worlds.load_version(second.version_id).ref.parent_version_id == first.version_id
    assert worlds.get_branch_head(root.game_id, root.branch_id).version_id == third.version_id


def test_bookmark_and_terminal_recovery_versions_are_protected(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    root = worlds.create_game_with_root(create_initial_state())
    first, state = _commit(root, worlds.load_version(root.version_id).state, "first")
    second, state = _commit(first, state, "second")
    third, _ = _commit(second, state, "third")
    worlds.create_bookmark(root.game_id, root.branch_id, first.version_id, "recovery")
    assert third.settlement_id is not None
    with saves._connect() as conn:
        conn.execute(
            """
            INSERT INTO terminal_records (
                id, game_id, branch_id, settlement_id, version_id,
                previous_version_id, facts_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', ?)
            """,
            (
                str(uuid4()),
                str(root.game_id),
                str(root.branch_id),
                str(third.settlement_id),
                str(third.version_id),
                str(second.version_id),
                third.created_at.isoformat(),
            ),
        )

    plan = worlds.plan_retention(root.game_id, root.branch_id, recent_limit=1)

    assert "bookmark" in plan.reasons[str(first.version_id)]
    assert "terminal_predecessor" in plan.reasons[str(second.version_id)]
    assert "terminal_version" in plan.reasons[str(third.version_id)]
    assert not {first.version_id, second.version_id, third.version_id} & set(plan.delete_version_ids)


def test_shared_fork_ancestor_is_protected_when_cleaning_one_branch(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    root = worlds.create_game_with_root(create_initial_state())
    first, state = _commit(root, worlds.load_version(root.version_id).state, "first")
    second, state = _commit(first, state, "second")
    third, _ = _commit(second, state, "third")
    fork = worlds.create_branch_from_version(first.version_id)

    plan = worlds.plan_retention(root.game_id, root.branch_id, recent_limit=1)

    assert str(first.version_id) in plan.protected_version_ids
    assert "branch_fork_root" in plan.reasons[str(first.version_id)]
    assert str(first.version_id) not in plan.delete_version_ids
    assert fork.parent_version_id == first.version_id
    assert str(third.version_id) not in plan.delete_version_ids


def test_existing_not_null_settlement_schema_is_migrated_for_gc(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    with saves._connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        conn.execute(
            """
            CREATE TABLE settlements_legacy (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                client_action_id TEXT NOT NULL,
                parent_version_id TEXT NOT NULL,
                facts_json TEXT NOT NULL,
                delta_json TEXT NOT NULL,
                attribution_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (game_id, branch_id, client_action_id),
                UNIQUE (game_id, branch_id, id)
            )
            """,
        )
        conn.execute(
            "INSERT INTO settlements_legacy SELECT id, game_id, branch_id, client_action_id, parent_version_id, facts_json, delta_json, attribution_json, created_at FROM settlements",
        )
        conn.execute("DROP TABLE settlements")
        conn.execute("ALTER TABLE settlements_legacy RENAME TO settlements")
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")

    worlds.init_worlds_db()
    with saves._connect() as conn:
        parent = next(row for row in conn.execute("PRAGMA table_info(settlements)") if row["name"] == "parent_version_id")
    assert parent["notnull"] == 0
