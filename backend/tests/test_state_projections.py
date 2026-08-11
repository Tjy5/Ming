from __future__ import annotations

from uuid import uuid4

from api.action_routes import get_world_state_projection
from api.action_service import ActionService
from db import saves, worlds
from engine.world_state import world_state_projection
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, MetricWorldDelta
from models.world import DeltaId, Duration, new_client_action_id


class _ProjectionAdjudicator:
    async def adjudicate(self, _intent, state):
        return AdjudicationProposal(
            result_tier="success",
            execution_status="completed",
            duration_candidate=Duration(unit="hour", value=1),
            duration_reason="投影测试行动",
            deltas=[
                MetricWorldDelta(
                    delta_id=DeltaId(uuid4()),
                    target_scope="world",
                    field="national_treasury",
                    operation="increment",
                    before_value=state.national_treasury,
                    value=5,
                ),
            ],
        )


def test_projection_carries_one_version_for_metrics_executors_and_regions(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "projection.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    snapshot = worlds.load_version(root.version_id)

    projection = world_state_projection(snapshot.state)
    endpoint_projection = get_world_state_projection(
        root.game_id,
        root.branch_id,
        root.version_id,
    )

    assert projection == endpoint_projection
    assert projection.version_id == root.version_id
    assert all(metric.version_id == root.version_id for metric in projection.metrics)
    assert all(item.version_id == root.version_id for item in projection.executors)
    assert all(
        item.executor.entity_type in {"person", "faction", "institution", "temporary_authority"}
        for item in projection.executors
    )
    assert all(region.version_id == root.version_id for region in projection.regions)


def test_projection_recent_sources_come_from_the_requested_version_settlement(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "projection-sources.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="增加国库",
        action_kind="governance",
    )
    committed = ActionService(adjudicator=_ProjectionAdjudicator()).execute_sync(intent)

    projection = get_world_state_projection(
        root.game_id,
        root.branch_id,
        committed.result.version.version_id,
    )
    treasury = next(
        metric
        for metric in projection.metrics
        if metric.target.metric_key == "national_treasury"
    )

    assert len(treasury.recent_sources) == 1
    assert treasury.recent_sources[0].actual_delta == 5
    assert treasury.recent_sources[0].after_value == committed.state.national_treasury
