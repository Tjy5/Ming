from __future__ import annotations

from uuid import uuid4

from api.action_routes import get_world_state_projection
from api.action_service import ActionService
from api.assembly_helpers import select_assembly_actor_views
from db import saves, worlds
from engine.world_state import world_state_projection
from models.enums import MinisterStatus, RegionControl
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, MetricWorldDelta
from models.world import (
    ASSEMBLY_PARTICIPATE_CAPABILITY,
    DeltaId,
    Duration,
    EntitySource,
    PermissionReference,
    PersonEntity,
    RegionEntity,
    new_client_action_id,
    new_entity_id,
    new_permission_id,
)
from models.world_state import ModifierRecord, ModifierTransform


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


def test_region_projection_exposes_same_version_metrics_local_entities_and_vacuum(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "region-projection.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    state = worlds.load_version(root.version_id).state
    region_entity = next(
        entity for entity in state.entity_registry.values()
        if isinstance(entity, RegionEntity)
    )
    legacy_region = next(
        region for region in state.regions if region.name == region_entity.legacy_name
    )
    legacy_region.control = RegionControl.UNSTABLE

    controller_id = new_entity_id()
    local_actor_id = new_entity_id()
    source = EntitySource(kind="adjudication", summary="当前分支生成的地区主体")
    state.entity_registry[controller_id] = PersonEntity(
        entity_id=controller_id,
        display_name="已瓦解守府",
        status="ended",
        available=False,
        source=source,
    )
    state.entity_registry[local_actor_id] = PersonEntity(
        entity_id=local_actor_id,
        display_name="本地义士",
        source=source,
        permissions=[PermissionReference(
            permission_id=new_permission_id(),
            capability="region.report",
            scope_entity_id=region_entity.entity_id,
        )],
    )
    state.entity_registry[region_entity.entity_id] = region_entity.model_copy(
        update={"controller_entity_id": controller_id},
    )
    now = state.time.clock
    assert now is not None
    modifier_id = "region-instability-test"
    state.world_state.modifiers[modifier_id] = ModifierRecord(
        modifier_id=modifier_id,
        name="战后秩序崩解",
        target={
            "target_scope": "region",
            "metric_key": "stability",
            "target_entity_id": region_entity.entity_id,
        },
        source_kind="event",
        source_ref="event:regional-collapse",
        transform=ModifierTransform(kind="add", amount=-100),
        started_at=now,
        ends_at=now.model_copy(update={"absolute_hour": now.absolute_hour + 24}),
        stacking_group="regional-instability",
    )

    projection = world_state_projection(state)
    region = next(item for item in projection.regions if item.region_id == region_entity.entity_id)
    stability = next(
        metric for metric in region.metrics if metric.target.metric_key == "stability"
    )

    assert all(metric.version_id == root.version_id for metric in region.metrics)
    assert all(metric.target.target_scope == "region" for metric in region.metrics)
    assert all(
        metric.target.target_entity_id == region_entity.entity_id
        for metric in region.metrics
    )
    assert stability.base_value == legacy_region.stability
    assert stability.effective_value == 0
    assert [item.modifier_id for item in stability.active_modifiers] == [modifier_id]
    assert region.local_entity_ids == sorted(
        [controller_id, local_actor_id],
        key=str,
    )
    assert region.danger is True
    assert any(factor.startswith("metric:stability:") for factor in region.danger_factors)
    assert "control:失控" in region.danger_factors
    assert region.power_vacuum is True
    assert region.power_vacuum_reasons == ["controller_ended"]


def test_region_projection_does_not_invent_vacuum_for_court_controlled_legacy_region(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "region-court-control.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    state = worlds.load_version(root.version_id).state
    court_region = next(
        region for region in state.regions
        if region.control == RegionControl.COURT
    )
    region_entity = next(
        entity for entity in state.entity_registry.values()
        if isinstance(entity, RegionEntity) and entity.legacy_name == court_region.name
    )
    projection = world_state_projection(state)
    projected_region = next(
        region for region in projection.regions
        if region.region_id == region_entity.entity_id
    )

    assert projected_region.display_name == court_region.name
    assert projected_region.version_id == root.version_id
    assert projected_region.controller_entity_id is None
    assert projected_region.power_vacuum is False
    assert projected_region.power_vacuum_reasons == []


def test_dynamic_capable_actor_is_selected_while_ended_actor_cannot_reappear(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "dynamic-assembly.db")
    saves.init_db()
    initial = create_initial_state()
    for minister in initial.ministers[:9]:
        minister.status = MinisterStatus.ACTIVE
    root = worlds.create_game_with_root(initial)
    state = worlds.load_version(root.version_id).state
    source = EntitySource(kind="adjudication", summary="当前分支推举的议事主体")

    active_id = new_entity_id()
    ended_id = new_entity_id()

    def permission() -> PermissionReference:
        return PermissionReference(
            permission_id=new_permission_id(),
            capability=ASSEMBLY_PARTICIPATE_CAPABILITY,
        )

    state.entity_registry[active_id] = PersonEntity(
        entity_id=active_id,
        display_name="新任参议",
        roles=["参议"],
        source=source,
        permissions=[permission()],
    )
    state.entity_registry[ended_id] = PersonEntity(
        entity_id=ended_id,
        display_name="已故旧臣",
        status="ended",
        available=False,
        source=source,
        permissions=[permission()],
    )

    selected = select_assembly_actor_views(state)
    selected_ids = {actor.entity_id for actor in selected}

    assert active_id in selected_ids
    assert ended_id not in selected_ids
    dynamic = next(actor for actor in selected if actor.entity_id == active_id)
    assert dynamic.entity_type == "person"
    assert ASSEMBLY_PARTICIPATE_CAPABILITY in dynamic.capabilities
    assert dynamic.capability_sources[0].startswith("permission:")
