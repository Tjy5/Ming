"""E2E: one clock across TRPG, milestones, settlements, and the 1368 boundary.

Run explicitly with ``RUN_E2E=1 python -m pytest tests -m e2e -q``. The
scenario is deterministic and uses only the test provider. Historical dates in
timeline data are narrative hints; they never overwrite the canonical clock.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from ai.provider import ResilientProvider
from api import state as api_state
from api import trpg as trpg_routes
from api.action_service import ActionService
from db import saves, worlds
from engine.calendar import set_game_time_projection
from engine.core import check_game_end
from fakes import FakeProvider
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal
from models.trpg import ActRequest
from models.world import Duration, new_client_action_id
from trpg import dice as dice_mod


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.getenv("RUN_E2E") != "1",
        reason="e2e dynamic-time scenario: set RUN_E2E=1",
    ),
]


MAIN_PATH_MILESTONES = [
    ("birth-1328", "childhood"),
    ("famine-1344", "monk_wanderer"),
    ("wandering-1345", "enlistment"),
    ("enlist-1352", "enlistment"),
    ("recruit-1353", "enlistment"),
    ("cross-yangtze-1355", "warlord"),
    ("yingtian-founding", "warlord"),
]


class _StaticAdjudicator:
    async def adjudicate(self, _intent, _state):
        return AdjudicationProposal(
            result_tier="success",
            execution_status="completed",
            duration_candidate=Duration(unit="month", value=2),
            duration_reason="跨越历史年份边界的显式等待",
        )


def _fake_provider():
    return ResilientProvider(FakeProvider(), timeout=1, retries=1)


@pytest.mark.e2e
def test_dynamic_time_world_clock_playthrough(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "dynamic-time-e2e.db")
    saves.init_db()
    dice_mod.set_seed(2026)
    api_state._provider = _fake_provider()
    api_state._state = create_initial_state()

    # Each TRPG act settles four hours and each milestone settles one hour.
    # Timeline years never jump the clock, while chapter/phase metadata advances.
    phase_switch_count = 0
    expected_absolute_hour = 0
    for milestone_id, expected_chapter in MAIN_PATH_MILESTONES:
        act = asyncio.run(
            trpg_routes.act(
                ActRequest(action_text="操练兵马，亲授阵法", attr="军事"),
            ),
        )
        expected_absolute_hour += 4
        assert act["time"]["clock"]["absolute_hour"] == expected_absolute_hour

        milestone = asyncio.run(trpg_routes.complete_milestone(milestone_id))
        expected_absolute_hour += 1
        state = api_state._state
        assert state.time.clock.absolute_hour == expected_absolute_hour
        assert (state.time.year, state.time.month) == (1328, 10)
        assert state.chapter == expected_chapter
        if milestone_id == "yingtian-founding":
            assert milestone["phase"] == "governance"
            phase_switch_count += 1
        else:
            assert milestone["phase"] == "life_story"
    assert phase_switch_count == 1

    # Start a deterministic boundary fixture just before 1368, then cross it
    # through the same ActionService/consumer/SQLite transaction used in play.
    boundary_state = create_initial_state()
    boundary_state.phase = "governance"
    set_game_time_projection(
        boundary_state.time,
        year=1367,
        month=12,
        migration_source="initial_world",
    )
    root = worlds.create_game_with_root(boundary_state)
    service = ActionService(adjudicator=_StaticAdjudicator())
    crossed = service.execute_sync(
        ActionIntent(
            game_id=root.game_id,
            branch_id=root.branch_id,
            expected_parent_version_id=root.version_id,
            client_action_id=new_client_action_id(),
            raw_text="等待两个月，继续观察沙盒世界",
            action_kind="wait",
            mode="governance",
        ),
    )

    assert (crossed.state.time.year, crossed.state.time.month) > (1368, 1)
    assert crossed.result.facts.time_plan is not None
    assert crossed.result.facts.time_plan.consumer_invocations
    assert check_game_end(crossed.state) is None
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 2

    dead = crossed.state.model_copy(deep=True)
    dead.player_world_status.life_status = "dead"
    assert check_game_end(dead) == {
        "result": "defeat",
        "message": "主角已死，当前世界线终结",
    }
