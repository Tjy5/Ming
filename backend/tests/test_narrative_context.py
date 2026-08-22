from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai.narrative_context import (
    MAX_DETAILED_ENTITIES,
    MAX_DISTANT_REGION_SUMMARY_TOKENS,
    build_narrative_context,
    build_persisted_narrative_context,
    project_narrative_context_for_prompt,
)
from db import saves, worlds
from engine.settlement import apply_world_deltas
from engine.tables import (
    REGION_ADJACENCY,
    REGION_NAMES,
    REGION_ORDER,
    validate_region_adjacency,
)
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, MetricWorldDelta
from models.world import RegionEntity, new_client_action_id, new_delta_id


def _committed_world(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "narrative-context.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    parent = worlds.load_version(root.version_id).state
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="开仓赈济",
        action_kind="decree",
    )
    proposal = AdjudicationProposal(
        result_tier="success",
        key_factors=["灾情已核实"],
        immediate_changes=["民心上升"],
        execution_status="completed",
        deltas=[
            MetricWorldDelta(
                delta_id=new_delta_id(),
                target_scope="world",
                field="civil_morale",
                operation="increment",
                before_value=parent.civil_morale,
                value=1,
            ),
        ],
    )
    changed = apply_world_deltas(parent, proposal.deltas)
    result = worlds.commit_settlement(intent, changed, proposal)
    state = worlds.load_version(result.version.version_id).state
    return root, state, result.facts


def _regional_context(monkeypatch, tmp_path, *, target_entity_count: int = 1):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "regional-context.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    parent = worlds.load_version(root.version_id).state
    region_id = next(
        entity_id
        for entity_id, entity in parent.entity_registry.items()
        if isinstance(entity, RegionEntity) and entity.legacy_name == "应天"
    )
    target_entity_ids = [
        entity_id
        for entity_id, entity in parent.entity_registry.items()
        if not isinstance(entity, RegionEntity)
    ][:target_entity_count]
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="开仓赈济应天",
        action_kind="decree",
        target_region_id=region_id,
        regional_targets=["应天"],
        target_entity_ids=target_entity_ids,
    )
    proposal = AdjudicationProposal(
        result_tier="success",
        key_factors=["应天灾情已核实"],
        immediate_changes=["应天稳定提升"],
        execution_status="completed",
    )
    result = worlds.commit_settlement(intent, parent, proposal)
    state = worlds.load_version(result.version.version_id).state
    return build_narrative_context(
        path_id="structured_action",
        state=state,
        settlement=result.facts,
        action_text=intent.raw_text,
    )


def test_context_uses_one_committed_version_for_all_sibling_facts(monkeypatch, tmp_path):
    root, state, facts = _committed_world(monkeypatch, tmp_path)
    from db.narrative_memory import append_memory

    memory = append_memory(
        game_id=root.game_id,
        branch_id=root.branch_id,
        source_version_id=root.version_id,
        mode="governance",
        phase=state.phase,
        chapter=state.chapter,
        topic_id="relief",
        kind="decision",
        role="user",
        content="决定开仓赈济",
        created_world_hour=0,
    )

    context = build_persisted_narrative_context(
        path_id="structured_action",
        state=state,
        settlement=facts,
        topic_id="relief",
        action_text="开仓赈济",
    )

    assert context.game_id == facts.game_id
    assert context.branch_id == facts.branch_id
    assert context.version_id == facts.result_version_id
    assert context.world_state.version_id == facts.result_version_id
    assert context.settlement_id == facts.settlement_id
    assert context.time.absolute_hour == context.time.calendar.absolute_hour
    assert [item.memory_id for item in context.memories] == [memory.memory_id]
    assert context.entities
    assert any(entity.display_name == "主角" for entity in context.entities)
    assert context.source_versions.narrative_registry == "narrative-paths-v1"
    assert context.regions == context.world_state.regions
    assert context.executor == facts.attribution.executor_facts
    assert context.rolls == facts.rolls


def test_settlement_required_path_rejects_legacy_or_wrong_version_context(
    monkeypatch,
    tmp_path,
):
    _root, state, facts = _committed_world(monkeypatch, tmp_path)
    with pytest.raises(ValidationError, match="requires committed settlement facts"):
        build_narrative_context(path_id="structured_action", state=state)

    mismatched = state.model_copy(deep=True)
    mismatched.world_metadata.version_id = uuid4()
    with pytest.raises(ValidationError, match="identity does not match"):
        build_narrative_context(
            path_id="structured_action",
            state=mismatched,
            settlement=facts,
        )


def test_person_scoped_path_requires_explicit_entity_scope(monkeypatch, tmp_path):
    _root, state, facts = _committed_world(monkeypatch, tmp_path)
    with pytest.raises(ValidationError, match="requires a person/entity scope"):
        build_narrative_context(
            path_id="entity_dialogue",
            state=state,
            settlement=facts,
        )


def test_region_adjacency_is_complete_symmetric_and_canonical():
    validate_region_adjacency()
    assert set(REGION_ADJACENCY) == set(REGION_NAMES)
    assert tuple(REGION_ORDER) == tuple(dict.fromkeys(REGION_ORDER))
    for region, neighbours in REGION_ADJACENCY.items():
        assert set(neighbours) <= set(REGION_NAMES)
        assert all(region in REGION_ADJACENCY[neighbour] for neighbour in neighbours)


def test_regional_projection_prunes_only_prompt_copy_and_preserves_facts(
    monkeypatch,
    tmp_path,
):
    context = _regional_context(monkeypatch, tmp_path)
    before = context.model_dump(mode="json", exclude_none=True)

    projection = project_narrative_context_for_prompt(context)

    assert projection.mode == "regional"
    expected_names = [
        name
        for name in REGION_ORDER
        if name == "应天" or name in REGION_ADJACENCY["应天"]
    ]
    assert projection.detailed_region_names == expected_names
    assert [item["display_name"] for item in projection.context["regions"]] == expected_names
    assert [item["name"] for item in projection.context["legacy_regions"]] == expected_names
    assert projection.context["world_state"]["regions"] == projection.context["regions"]
    assert len(projection.context["entities"]) <= MAX_DETAILED_ENTITIES
    assert projection.distant_region_summary_tokens <= (
        MAX_DISTANT_REGION_SUMMARY_TOKENS
    )
    assert all(
        set(summary) == {"name", "control", "stability", "threat"}
        for summary in projection.context["distant_region_summaries"]
    )
    for key in (
        "source_versions",
        "time",
        "player",
        "activities",
        "current_activity",
        "events",
        "policies",
        "settlement",
        "memories",
    ):
        assert projection.context.get(key) == before.get(key)
    assert projection.context["world_state"]["metrics"] == before["world_state"]["metrics"]
    assert context.model_dump(mode="json", exclude_none=True) == before


def test_related_entity_overflow_uses_bounded_role_summaries(monkeypatch, tmp_path):
    context = _regional_context(monkeypatch, tmp_path, target_entity_count=18)

    projection = project_narrative_context_for_prompt(context)

    assert projection.mode == "regional"
    assert len(projection.detailed_entity_ids) == MAX_DETAILED_ENTITIES
    assert projection.context["entity_summaries"]
    assert all(
        set(summary) == {"display_name", "entity_type", "role_status"}
        for summary in projection.context["entity_summaries"]
    )


@pytest.mark.parametrize(
    ("fact_updates", "reason"),
    [
        ({"regional_targets": [], "target_region_ids": []}, "regional_target_absent"),
        ({"regional_targets": ["未知政区"]}, "unknown_regional_target"),
        (
            {"regional_targets": ["应天", "杭州", "大都"], "target_region_ids": []},
            "detailed_region_limit_exceeded",
        ),
        ({"target_entity_ids": [uuid4()]}, "related_entity_unresolved"),
    ],
)
def test_unsafe_regional_projection_falls_back_to_full_context(
    monkeypatch,
    tmp_path,
    fact_updates,
    reason,
):
    context = _regional_context(monkeypatch, tmp_path)
    facts = context.settlement.model_copy(update=fact_updates)
    candidate = context.model_copy(update={"settlement": facts})

    projection = project_narrative_context_for_prompt(candidate)

    assert projection.mode == "full"
    assert projection.fallback_reason == reason
    assert projection.context == candidate.model_dump(mode="json", exclude_none=True)


def test_cross_region_relationship_falls_back_to_full_context(monkeypatch, tmp_path):
    context = _regional_context(monkeypatch, tmp_path)
    target_id = context.settlement.target_entity_ids[0]
    entities = [
        entity.model_copy(update={"relationship_ids": ["unresolved-cross-region"]})
        if entity.entity_id == target_id
        else entity
        for entity in context.entities
    ]
    candidate = context.model_copy(update={"entities": entities})

    projection = project_narrative_context_for_prompt(candidate)

    assert projection.mode == "full"
    assert projection.fallback_reason == "cross_region_relationship_unresolved"


def test_incomplete_canonical_region_facts_fall_back_to_full_context(
    monkeypatch,
    tmp_path,
):
    context = _regional_context(monkeypatch, tmp_path)
    incomplete_regions = context.regions[:-1]
    world_state = context.world_state.model_copy(update={"regions": incomplete_regions})
    candidate = context.model_copy(update={
        "regions": incomplete_regions,
        "world_state": world_state,
    })

    projection = project_narrative_context_for_prompt(candidate)

    assert projection.mode == "full"
    assert projection.fallback_reason == "canonical_region_facts_incomplete"
