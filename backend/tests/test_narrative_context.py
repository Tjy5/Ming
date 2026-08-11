from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai.narrative_context import (
    build_narrative_context,
    build_persisted_narrative_context,
)
from db import saves, worlds
from engine.settlement import apply_world_deltas
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, MetricWorldDelta
from models.world import new_client_action_id, new_delta_id


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
