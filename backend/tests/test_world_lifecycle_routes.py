from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api import state as api_state
from db import narrative_memory, saves, worlds
from engine.settlement import apply_world_deltas
from main import app
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, MetricWorldDelta
from models.world import new_client_action_id, new_delta_id


@pytest.fixture(autouse=True)
def _isolated_world_store(monkeypatch, tmp_path):
    old_state = api_state._state
    old_ref = api_state._get_world_head_ref()
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "world-lifecycle.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    try:
        yield
    finally:
        api_state._state = old_state
        api_state._world_head_cache.restore_ref(old_ref)


def _append_chat_memory(ref, content: str):
    state = worlds.load_version(ref.version_id).state
    assert state.time.clock is not None
    return narrative_memory.append_memory(
        game_id=ref.game_id,
        branch_id=ref.branch_id,
        source_version_id=ref.version_id,
        source_settlement_id=ref.settlement_id,
        mode="chat",
        phase=state.phase,
        chapter=state.chapter,
        topic_id="shared-topic",
        kind="raw_recent",
        role="assistant",
        content=content,
        created_world_hour=state.time.clock.absolute_hour,
    )


def _visible_chat_content(ref) -> list[str]:
    return [
        item.content
        for item in narrative_memory.list_visible_memories(
            game_id=ref.game_id,
            branch_id=ref.branch_id,
            version_id=ref.version_id,
            mode="chat",
            topic_id="shared-topic",
        )
    ]


def _commit_morale_change(root, amount: int):
    parent = worlds.load_version(root.version_id).state
    delta = MetricWorldDelta(
        delta_id=new_delta_id(),
        target_scope="world",
        field="civil_morale",
        operation="increment",
        before_value=parent.civil_morale,
        value=amount,
    )
    changed = apply_world_deltas(parent, [delta])
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="安抚民心",
        action_kind="decree",
    )
    proposal = AdjudicationProposal(
        result_tier="success",
        key_factors=["当前分支民情"],
        immediate_changes=["民心改善"],
        execution_status="completed",
        deltas=[delta],
    )
    return worlds.commit_settlement(intent, changed, proposal)


def test_public_branch_lifecycle_restores_state_and_ancestry_scoped_memory():
    root = worlds.create_game_with_root(create_initial_state())
    root_state = worlds.load_version(root.version_id).state
    _append_chat_memory(root, "共同祖先记忆")
    committed = _commit_morale_change(root, 7)
    _append_chat_memory(committed.version, "原分支分叉后记忆")
    source_snapshot = worlds.load_version(committed.version.version_id)
    api_state._publish_world_head(source_snapshot.state, source_snapshot.ref)

    with TestClient(app) as client:
        branches_response = client.get(f"/api/worlds/{root.game_id}/branches")
        assert branches_response.status_code == 200
        assert [item["branch_id"] for item in branches_response.json()["branches"]] == [
            str(root.branch_id),
        ]

        versions_response = client.get(
            f"/api/worlds/{root.game_id}/{root.branch_id}/versions",
        )
        assert versions_response.status_code == 200
        assert [item["version_id"] for item in versions_response.json()["versions"]] == [
            str(root.version_id),
            str(committed.version.version_id),
        ]

        fork_response = client.post(
            "/api/worlds/fork",
            json={
                "game_id": str(root.game_id),
                "branch_id": str(root.branch_id),
                "version_id": str(root.version_id),
            },
        )
        assert fork_response.status_code == 200
        fork_body = fork_response.json()
        assert fork_body["branch"]["parent_branch_id"] == str(root.branch_id)
        assert fork_body["branch"]["forked_from_version_id"] == str(root.version_id)
        assert fork_body["branch"]["head_version_id"] == fork_body["version"]["version_id"]
        assert fork_body["state"]["civil_morale"] == root_state.civil_morale

        fork_ref = api_state._get_world_head_ref()
        assert fork_ref is not None
        assert fork_ref.branch_id != root.branch_id
        assert _visible_chat_content(fork_ref) == ["共同祖先记忆"]
        _append_chat_memory(fork_ref, "仅子分支可见")

        switch_source = client.post(
            "/api/worlds/switch",
            json={
                "game_id": str(root.game_id),
                "branch_id": str(root.branch_id),
            },
        )
        assert switch_source.status_code == 200
        assert switch_source.json()["version"]["version_id"] == str(
            committed.version.version_id,
        )
        assert switch_source.json()["state"]["civil_morale"] == root_state.civil_morale + 7
        assert _visible_chat_content(committed.version) == [
            "共同祖先记忆",
            "原分支分叉后记忆",
        ]

        switch_fork = client.post(
            "/api/worlds/switch",
            json={
                "game_id": str(fork_ref.game_id),
                "branch_id": str(fork_ref.branch_id),
            },
        )
        assert switch_fork.status_code == 200
        assert switch_fork.json()["state"]["civil_morale"] == root_state.civil_morale
        assert _visible_chat_content(fork_ref) == [
            "共同祖先记忆",
            "仅子分支可见",
        ]

        branches_after_fork = client.get(
            f"/api/worlds/{root.game_id}/branches",
        ).json()["branches"]
        assert len(branches_after_fork) == 2


def test_foreign_world_identifiers_return_404_without_switching_runtime_head():
    root = worlds.create_game_with_root(create_initial_state())
    snapshot = worlds.load_version(root.version_id)
    api_state._publish_world_head(snapshot.state, snapshot.ref)
    before_ref = api_state._get_world_head_ref()
    before_state = api_state._get_state().model_dump()
    branch_count = len(worlds.list_branches(root.game_id))

    with TestClient(app) as client:
        foreign_game = client.post(
            "/api/worlds/switch",
            json={
                "game_id": str(uuid4()),
                "branch_id": str(root.branch_id),
            },
        )
        assert foreign_game.status_code == 404
        assert foreign_game.json()["detail"]["error_code"] == "world_not_found"

        foreign_branch = client.post(
            "/api/worlds/fork",
            json={
                "game_id": str(root.game_id),
                "branch_id": str(uuid4()),
                "version_id": str(root.version_id),
            },
        )
        assert foreign_branch.status_code == 404
        assert foreign_branch.json()["detail"]["error_code"] == "world_not_found"

        missing_versions = client.get(
            f"/api/worlds/{root.game_id}/{uuid4()}/versions",
        )
        assert missing_versions.status_code == 404
        assert missing_versions.json()["detail"]["error_code"] == "world_not_found"

    assert api_state._get_world_head_ref() == before_ref
    assert api_state._get_state().model_dump() == before_state
    assert len(worlds.list_branches(root.game_id)) == branch_count
