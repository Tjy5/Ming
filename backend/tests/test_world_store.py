from __future__ import annotations

import sqlite3

import pytest

from db import saves, worlds
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, MetricWorldDelta
from models.world import (
    EntitySource,
    FactionEntity,
    PersonEntity,
    PlayerWorldStatus,
    RegionEntity,
    new_branch_id,
    new_client_action_id,
    new_delta_id,
    new_entity_id,
)


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
    assert state.entity_registry == {}
    assert len(stored.state.entity_registry) == (
        len(state.ministers) + len(state.factions) + len(state.regions) + 1
    )
    assert sum(
        isinstance(entity, PersonEntity)
        for entity in stored.state.entity_registry.values()
    ) == len(state.ministers) + 1
    assert sum(
        isinstance(entity, FactionEntity)
        for entity in stored.state.entity_registry.values()
    ) == len(state.factions)
    assert sum(
        isinstance(entity, RegionEntity)
        for entity in stored.state.entity_registry.values()
    ) == len(state.regions)
    assert all(
        entity.origin_version_id == root.version_id
        and entity.source.kind == "initial_data"
        and entity.source.reference == "yuanming-initial-v1"
        for entity in stored.state.entity_registry.values()
    )
    player_id = stored.state.player_world_status.player_character_id
    assert player_id in stored.state.entity_registry
    assert "player_character" in stored.state.entity_registry[player_id].roles
    projected_ministers = {
        entity.legacy_name: entity
        for entity in stored.state.entity_registry.values()
        if isinstance(entity, PersonEntity) and entity.legacy_name != "主角"
    }
    for minister in state.ministers:
        status = getattr(minister.status, "value", str(minister.status))
        assert projected_ministers[minister.name].available == (
            status in {"active", "idle", "on_mission"}
        )

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


def test_root_creation_preserves_existing_registry_instead_of_reprojecting_static_lists(
    monkeypatch,
    tmp_path,
):
    _init_store(monkeypatch, tmp_path)
    state = create_initial_state()
    player_id = new_entity_id()
    player = PersonEntity(
        entity_id=player_id,
        display_name="自定义主角",
        source=EntitySource(kind="system", reference="custom-world"),
        roles=["player_character"],
    )
    state.entity_registry = {player_id: player}
    state.player_world_status = PlayerWorldStatus(
        player_character_id=player_id,
        identity_summary="自定义世界身份",
    )

    root = worlds.create_game_with_root(state)
    stored = worlds.load_version(root.version_id)

    assert stored.state.entity_registry == {
        player_id: player.model_copy(update={"origin_version_id": root.version_id}),
    }
    assert stored.state.player_world_status == state.player_world_status
    assert state.entity_registry == {player_id: player}


def test_root_creation_completes_missing_player_identity_without_rebuilding_registry(
    monkeypatch,
    tmp_path,
):
    _init_store(monkeypatch, tmp_path)
    state = create_initial_state()
    existing_id = new_entity_id()
    existing = PersonEntity(
        entity_id=existing_id,
        display_name="既有动态人物",
        source=EntitySource(kind="system", reference="custom-world"),
    )
    state.entity_registry = {existing_id: existing}

    root = worlds.create_game_with_root(state)
    stored = worlds.load_version(root.version_id).state

    assert stored.entity_registry[existing_id] == existing.model_copy(
        update={"origin_version_id": root.version_id},
    )
    assert len(stored.entity_registry) == 2
    player_id = stored.player_world_status.player_character_id
    assert player_id != existing_id
    assert isinstance(stored.entity_registry[player_id], PersonEntity)
    assert "player_character" in stored.entity_registry[player_id].roles


def test_root_entity_source_matches_explicit_legacy_source_kind(monkeypatch, tmp_path):
    _init_store(monkeypatch, tmp_path)

    root = worlds.create_game_with_root(
        create_initial_state(),
        source_kind="legacy_save",
        source_ref="42",
    )
    stored = worlds.load_version(root.version_id).state

    assert stored.world_metadata.source_kind == "legacy_save"
    assert all(
        entity.source.kind == "legacy_save" and entity.source.reference == "42"
        for entity in stored.entity_registry.values()
    )


def test_root_projection_rejects_ambiguous_duplicate_legacy_names(monkeypatch, tmp_path):
    _init_store(monkeypatch, tmp_path)
    state = create_initial_state()
    state.factions.append(state.factions[0].model_copy(deep=True))

    with pytest.raises(worlds.WorldCorruptDataError, match="faction names"):
        worlds.create_game_with_root(state)


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
    initial = worlds.load_version(root.version_id).state
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
    initial = worlds.load_version(root.version_id).state
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
    initial = worlds.load_version(root.version_id).state
    changed = initial.model_copy(deep=True)
    changed.civil_morale -= 2

    result = worlds.commit_settlement(
        _action(root, text="尝试失败但形成后果"),
        changed,
        _proposal(initial.civil_morale, -2, tier="failure"),
    )

    assert result.facts.result_tier == "failure"
    assert worlds.get_branch_head(root.game_id, root.branch_id) == result.version
    committed = worlds.load_version(result.version.version_id).state
    assert committed.civil_morale == changed.civil_morale
    assert committed.entity_registry == initial.entity_registry
    assert committed.player_world_status == initial.player_world_status
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1


def test_repository_rejects_committed_state_that_drops_registered_identity(
    monkeypatch,
    tmp_path,
):
    _init_store(monkeypatch, tmp_path)
    root = worlds.create_game_with_root(create_initial_state())
    initial = worlds.load_version(root.version_id).state
    changed = initial.model_copy(deep=True)
    removed_id = next(iter(changed.entity_registry))
    del changed.entity_registry[removed_id]
    changed.civil_morale += 1

    with pytest.raises(worlds.WorldCorruptDataError, match="cannot remove identities"):
        worlds.commit_settlement(
            _action(root, text="非法删除主体"),
            changed,
            _proposal(initial.civil_morale, 1),
        )

    assert worlds.get_branch_head(root.game_id, root.branch_id) == root
    assert worlds.list_settlements(root.game_id, root.branch_id) == []
