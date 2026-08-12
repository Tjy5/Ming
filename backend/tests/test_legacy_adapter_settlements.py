from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from api import state as api_state
from api import routes, trpg
from api.assembly_routes import (
    assembly_decree,
    assembly_petition,
    assembly_rage,
    assembly_start,
    assembly_vote,
    silence_assembly,
)
from api.schemas import AssemblyDecreeRequest, AssemblyRageRequest, AssemblyVoteRequest
from db import saves, worlds
from fakes import FakeProvider
from models.enums import AssemblyPhase
from models.game import GameTime, create_initial_state
from models.trpg import ConvergeRequest


@pytest.fixture(autouse=True)
def _isolated_world_store(monkeypatch, tmp_path):
    old_state = api_state._state
    old_ref = api_state._get_world_head_ref()
    old_provider = api_state._provider
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "legacy-adapters.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    api_state._provider = FakeProvider()
    api_state._state = create_initial_state()
    try:
        yield
    finally:
        api_state._state = old_state
        api_state._provider = old_provider
        api_state._world_head_cache.restore_ref(old_ref)


def _assert_settled(response: dict, *, previous_version=None):
    settlement_id = response["settlement_id"]
    version_id = response["context_version_id"]
    assert settlement_id is not None
    assert version_id is not None
    assert worlds.get_settlement(settlement_id).result_version_id == version_id
    ref = api_state._get_world_head_ref()
    assert ref is not None and ref.version_id == version_id
    if previous_version is not None:
        assert version_id != previous_version


def test_milestone_and_convergence_use_one_settlement_each():
    first = asyncio.run(trpg.complete_milestone("famine-1344"))
    _assert_settled(first)
    first_version = first["context_version_id"]
    with pytest.raises(HTTPException):
        asyncio.run(trpg.complete_milestone("famine-1344"))
    ref = api_state._get_world_head_ref()
    assert ref is not None
    assert len(worlds.list_versions(ref.game_id, ref.branch_id)) == 2

    # Reset to a pending convergence state while preserving the same isolated DB.
    state = create_initial_state()
    state.chapter = "warlord"
    state.time = GameTime(year=1360, month=3, era_name="至正", era_year=20)
    api_state._world_head_cache.clear()
    api_state._state = state
    converged = asyncio.run(trpg.converge(ConvergeRequest(choice="accept")))
    _assert_settled(converged, previous_version=first_version)


@pytest.mark.asyncio
async def test_assembly_legacy_adapters_return_settlement_and_version():
    started = await assembly_start()
    _assert_settled(started)
    started_version = started["context_version_id"]

    petitioned = await assembly_petition()
    _assert_settled(petitioned, previous_version=started_version)

    # Vote consumes the committed participants; move the compatibility view to
    # debate phase before invoking the adapter.
    api_state._state.last_assembly.phase = AssemblyPhase.DEBATE
    voted = await assembly_vote(AssemblyVoteRequest())
    _assert_settled(voted, previous_version=petitioned["context_version_id"])

    # Rage and legacy silence are independent state-only adapters in fresh
    # branches, so each is exercised after creating a new assembly head.
    api_state._world_head_cache.clear()
    api_state._state = create_initial_state()
    started_again = await assembly_start()
    target_faction = api_state._state.factions[0].name
    raged = await assembly_rage(AssemblyRageRequest(target_faction=target_faction))
    _assert_settled(raged, previous_version=started_again["context_version_id"])

    api_state._world_head_cache.clear()
    api_state._state = create_initial_state()
    await assembly_start()
    silenced = await silence_assembly()
    _assert_settled(silenced)


@pytest.mark.asyncio
async def test_assembly_decree_commits_state_once_with_settlement_version():
    await assembly_start()
    await assembly_petition()
    api_state._state.last_assembly.phase = AssemblyPhase.DEBATE
    voted = await assembly_vote(AssemblyVoteRequest())
    previous_version = voted["context_version_id"]

    response = await assembly_decree(AssemblyDecreeRequest(decision="adopt"))
    _assert_settled(response, previous_version=previous_version)
    assert response["state"] == api_state._get_state().model_dump()
    assert (
        worlds.load_version(response["context_version_id"]).state.model_dump()
        == response["state"]
    )
    assert response["assembly"]["final_decision"] == "adopt"

    ref = api_state._get_world_head_ref()
    assert ref is not None
    version_count = len(worlds.list_versions(ref.game_id, ref.branch_id))
    with pytest.raises(HTTPException):
        await assembly_decree(AssemblyDecreeRequest(decision="adopt"))
    assert len(worlds.list_versions(ref.game_id, ref.branch_id)) == version_count


@pytest.mark.asyncio
async def test_debate_silence_uses_unified_settlement():
    response = await routes.silence_debate()
    _assert_settled(response)
    assert response["prestige_change"] >= 0
