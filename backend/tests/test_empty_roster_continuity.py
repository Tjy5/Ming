from __future__ import annotations

import pytest

from api import state as api_state
from api.assembly_routes import assembly_petition, assembly_start
from api.continuity_service import ensure_governance_continuity
from db import saves, worlds
from engine.continuity import detect_governance_vacuum
from models.settlement import LifecycleWorldDelta
from fakes import FakeProvider
from models.enums import MinisterStatus
from models.game import create_initial_state


@pytest.fixture(autouse=True)
def _isolated_world_store(monkeypatch, tmp_path):
    old_state = api_state._state
    old_ref = api_state._get_world_head_ref()
    old_provider = api_state._provider
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "empty-roster.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    api_state._provider = FakeProvider()
    try:
        yield
    finally:
        api_state._state = old_state
        api_state._provider = old_provider
        api_state._world_head_cache.restore_ref(old_ref)


def _all_ministers_removed():
    state = create_initial_state()
    for minister in state.ministers:
        minister.status = MinisterStatus.REMOVED
    api_state._state = state
    return state


def test_continuity_commits_person_and_non_person_once():
    _all_ministers_removed()
    _root_state, root_ref = api_state._ensure_world_head()

    settled = ensure_governance_continuity()

    assert settled is not None
    assert not detect_governance_vacuum(settled)
    created = [
        entity
        for entity in settled.entity_registry.values()
        if entity.created_by_settlement_id is not None
        and entity.created_by_settlement_id != root_ref.settlement_id
    ]
    assert {entity.entity_type for entity in created} >= {"person", "temporary_authority"}
    settlement_ids = {entity.created_by_settlement_id for entity in created}
    assert len(settlement_ids) == 1
    continuity_settlement = worlds.list_settlements(root_ref.game_id, root_ref.branch_id)[0]
    assert settled.player_world_status.actionable_goal_ids == [
        "world_continuity_required",
    ]
    assert any(isinstance(delta, LifecycleWorldDelta) for delta in continuity_settlement.deltas)

    # The settled head is no longer a vacuum, so retries do not create another
    # continuity settlement or duplicate identities.
    assert ensure_governance_continuity() is None
    head = worlds.load_branch_head(root_ref.game_id, root_ref.branch_id)
    assert head.ref.parent_version_id == root_ref.version_id


@pytest.mark.asyncio
async def test_public_assembly_start_and_petition_recover_empty_roster():
    _all_ministers_removed()

    started = await assembly_start()
    assert len(started["participants"]) >= 1
    assert {item["entity_type"] for item in started["participants"]} >= {
        "person",
        "temporary_authority",
    }

    petitioned = await assembly_petition()
    assert len(petitioned["petitions"]) == len(started["participants"])
    assert all(item["minister_name"] for item in petitioned["petitions"])
