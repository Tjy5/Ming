from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .world import (
    BranchId,
    ClientActionId,
    DeltaId,
    EntityId,
    GameId,
    SettlementId,
    VersionId,
    WorldEntity,
    WorldVersionRef,
)


JsonScalar = str | int | float | bool | None
ResultTier = Literal["success", "partial_success", "failure"]


class _SettlementContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionIntent(_SettlementContract):
    schema_version: Literal[1] = 1
    game_id: GameId
    branch_id: BranchId
    expected_parent_version_id: VersionId
    client_action_id: ClientActionId
    raw_text: str = Field(min_length=1)
    action_kind: str | None = None
    suggestion_id: str | None = None
    requested_executor_id: EntityId | None = None
    target_region_id: EntityId | None = None
    target_entity_ids: list[EntityId] = Field(default_factory=list)
    mode: str | None = None
    topic: str | None = None
    visible_context_version: str | None = None

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(
            mode="json",
            exclude={
                "game_id",
                "branch_id",
                "expected_parent_version_id",
                "client_action_id",
            },
        )

    def payload_hash(self) -> str:
        canonical = json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


class FieldChange(_SettlementContract):
    field: str
    before_value: JsonScalar = None
    value: JsonScalar


class MetricWorldDelta(_SettlementContract):
    delta_type: Literal["metric"] = "metric"
    delta_id: DeltaId
    target_scope: Literal["world", "region", "entity"]
    target_id: EntityId | None = None
    field: str
    operation: Literal["increment", "set"]
    before_value: JsonScalar = None
    value: JsonScalar
    source_proposal: str | None = None


class EntityWorldDelta(_SettlementContract):
    delta_type: Literal["entity"] = "entity"
    delta_id: DeltaId
    operation: Literal["create", "update", "end"]
    target_entity_id: EntityId
    before_status: str | None = None
    entity: WorldEntity | None = None
    changes: list[FieldChange] = Field(default_factory=list)
    source_proposal: str | None = None


class RelationshipWorldDelta(_SettlementContract):
    delta_type: Literal["relationship"] = "relationship"
    delta_id: DeltaId
    operation: Literal["create", "update", "end", "grant", "revoke", "assign"]
    from_entity_id: EntityId
    to_entity_id: EntityId
    relationship_type: str
    before_status: str | None = None
    next_status: str | None = None
    source_proposal: str | None = None


class LifecycleWorldDelta(_SettlementContract):
    delta_type: Literal["lifecycle"] = "lifecycle"
    delta_id: DeltaId
    transition_type: Literal["goal", "event", "activity"]
    transition_id: str
    before_status: str | None = None
    next_status: str
    source_proposal: str | None = None


class PlayerWorldDelta(_SettlementContract):
    delta_type: Literal["player"] = "player"
    delta_id: DeltaId
    operation: Literal["identity", "freedom", "location", "death"]
    before_value: str | None = None
    value: str
    trigger_action: ClientActionId | None = None
    direct_cause: str | None = None
    key_factors: list[str] = Field(default_factory=list)
    causal_summary: str | None = None
    source_proposal: str | None = None


class ModifierWorldDelta(_SettlementContract):
    delta_type: Literal["modifier"] = "modifier"
    delta_id: DeltaId
    operation: Literal["create", "update", "end"]
    modifier_id: str
    target_entity_id: EntityId | None = None
    before_value: JsonScalar = None
    value: JsonScalar
    source_proposal: str | None = None


WorldDelta = Annotated[
    MetricWorldDelta
    | EntityWorldDelta
    | RelationshipWorldDelta
    | LifecycleWorldDelta
    | PlayerWorldDelta
    | ModifierWorldDelta,
    Field(discriminator="delta_type"),
]


class ProviderAttribution(_SettlementContract):
    provider: str | None = None
    provider_type: str | None = None
    model: str | None = None
    request_id: str | None = None


class AdjudicationProposal(_SettlementContract):
    schema_version: Literal[1] = 1
    result_tier: ResultTier
    key_factors: list[str] = Field(default_factory=list)
    immediate_changes: list[str] = Field(default_factory=list)
    long_term_risks: list[str] = Field(default_factory=list)
    new_opportunities: list[str] = Field(default_factory=list)
    requested_executor_id: EntityId | None = None
    actual_executor_id: EntityId | None = None
    execution_status: Literal[
        "not_attempted",
        "attempted",
        "completed",
        "blocked",
        "failed",
    ] = "not_attempted"
    duration_candidate: str | None = None
    activity_candidate: str | None = None
    uncertainty: float | None = Field(default=None, ge=0, le=1)
    deltas: list[WorldDelta] = Field(default_factory=list)
    provider: ProviderAttribution = Field(default_factory=ProviderAttribution)


class SettlementAttribution(_SettlementContract):
    requested_executor_id: EntityId | None = None
    actual_executor_id: EntityId | None = None
    execution_status: str
    provider: ProviderAttribution


class SettlementFacts(_SettlementContract):
    schema_version: Literal[1] = 1
    settlement_id: SettlementId
    game_id: GameId
    branch_id: BranchId
    client_action_id: ClientActionId
    parent_version_id: VersionId
    result_version_id: VersionId
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_tier: ResultTier
    key_factors: list[str] = Field(default_factory=list)
    immediate_changes: list[str] = Field(default_factory=list)
    long_term_risks: list[str] = Field(default_factory=list)
    new_opportunities: list[str] = Field(default_factory=list)
    deltas: list[WorldDelta] = Field(default_factory=list)
    attribution: SettlementAttribution
    committed_at: datetime


class SettlementCommitResult(_SettlementContract):
    replayed: bool = False
    version: WorldVersionRef
    facts: SettlementFacts


class ActionRequestRecord(_SettlementContract):
    game_id: GameId
    branch_id: BranchId
    client_action_id: ClientActionId
    expected_parent_version_id: VersionId
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["pending", "completed"]
    settlement_id: SettlementId | None = None
    version_id: VersionId | None = None
    created_at: datetime
    updated_at: datetime
