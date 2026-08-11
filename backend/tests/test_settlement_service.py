from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from models.game import GameState, create_initial_state
from models.settlement import (
    ActionIntent,
    AdjudicationProposal,
    MetricWorldDelta,
)
from models.world import (
    Duration,
    new_branch_id,
    new_client_action_id,
    new_delta_id,
    new_game_id,
    new_version_id,
)


def _intent(raw_text: str = "整修河道") -> ActionIntent:
    return ActionIntent(
        game_id=new_game_id(),
        branch_id=new_branch_id(),
        expected_parent_version_id=new_version_id(),
        client_action_id=new_client_action_id(),
        raw_text=raw_text,
        action_kind="decree",
        target_entity_ids=[],
        mode="governance",
        topic="河工",
        visible_context_version="context-v1",
    )


def test_action_identity_is_uuid_typed_and_payload_hash_is_canonical():
    intent = _intent()
    dumped = intent.model_dump(mode="json")

    assert isinstance(intent.game_id, UUID)
    assert isinstance(dumped["game_id"], str)
    assert intent.payload_hash() == ActionIntent.model_validate(dumped).payload_hash()

    identity_only_change = intent.model_copy(
        update={"client_action_id": new_client_action_id()},
    )
    assert identity_only_change.payload_hash() == intent.payload_hash()

    payload_change = intent.model_copy(update={"raw_text": "开凿新河"})
    assert payload_change.payload_hash() != intent.payload_hash()


def test_adjudication_contract_accepts_legal_failure_and_rejects_unknown_fields():
    proposal = AdjudicationProposal(
        result_tier="failure",
        key_factors=["河堤失修"],
        immediate_changes=["民力受损"],
        long_term_risks=["来年水患"],
        new_opportunities=["重新勘测河道"],
        execution_status="attempted",
        deltas=[
            MetricWorldDelta(
                delta_id=new_delta_id(),
                target_scope="world",
                field="civil_morale",
                operation="increment",
                before_value=62,
                value=-2,
            ),
        ],
    )

    assert proposal.result_tier == "failure"
    assert proposal.deltas[0].delta_type == "metric"

    with pytest.raises(ValidationError):
        AdjudicationProposal.model_validate(
            {**proposal.model_dump(mode="json"), "unexpected": "must-not-be-ignored"},
        )


def test_adjudication_duration_is_structured_and_requires_a_paired_reason():
    proposal = AdjudicationProposal(
        result_tier="success",
        duration_candidate=Duration(unit="day", value=2),
        duration_reason="整修河道需要连续施工",
    )

    restored = AdjudicationProposal.model_validate(proposal.model_dump(mode="json"))
    assert restored.duration_candidate == Duration(unit="day", value=2)
    assert restored.duration_reason == "整修河道需要连续施工"

    with pytest.raises(ValidationError):
        AdjudicationProposal(result_tier="success", duration_candidate="两天")
    with pytest.raises(ValidationError):
        AdjudicationProposal(
            result_tier="success",
            duration_candidate=Duration(unit="day", value=2),
        )
    with pytest.raises(ValidationError):
        AdjudicationProposal(
            result_tier="success",
            duration_reason="不能脱离 duration 单独存在",
        )


def test_old_game_state_payload_gets_additive_world_defaults():
    payload = create_initial_state().model_dump(mode="json")
    payload.pop("world_metadata", None)
    payload.pop("entity_registry", None)
    payload.pop("player_world_status", None)

    restored = GameState.model_validate(payload)

    assert restored.world_metadata.schema_version == 1
    assert restored.entity_registry == {}
    assert restored.player_world_status.life_status == "alive"
