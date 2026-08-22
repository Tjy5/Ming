from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .world import (
    ActivityId,
    BranchId,
    ClientActionId,
    CheckpointId,
    DeltaId,
    Duration,
    ElapsedSegmentPlan,
    EntityId,
    GameId,
    PendingActivityDecision,
    PermissionId,
    PermissionReference,
    RelationId,
    SettlementId,
    TerminalRecordId,
    VersionId,
    WorldEntity,
    WorldInstant,
    WorldVersionRef,
)
from .world_state import (
    AppliedMetricAttribution,
    CommitmentRecord,
    ExecutorFacts,
    ModifierRecord,
    RollRecord,
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
    regional_targets: list[str] = Field(default_factory=list)
    target_entity_ids: list[EntityId] = Field(default_factory=list)
    mode: str | None = None
    topic: str | None = None
    visible_context_version: str | None = None
    activity_id: ActivityId | None = None
    checkpoint_id: CheckpointId | None = None
    checkpoint_sequence: int | None = Field(default=None, strict=True, ge=1)
    activity_command: Literal[
        "continue",
        "pause",
        "cancel",
        "redirect",
        "reassign",
        "resume",
    ] | None = None
    redirect_text: str | None = Field(default=None, min_length=1, max_length=4000)
    replacement_executor_id: EntityId | None = None

    @model_validator(mode="after")
    def _validate_activity_command(self) -> ActionIntent:
        command_fields = (
            self.activity_id,
            self.checkpoint_id,
            self.checkpoint_sequence,
            self.activity_command,
        )
        if any(value is not None for value in command_fields) and any(
            value is None for value in command_fields
        ):
            raise ValueError(
                "activity commands require activity_id, checkpoint_id, "
                "checkpoint_sequence, and activity_command",
            )
        if self.activity_command == "redirect" and self.redirect_text is None:
            raise ValueError("redirect activity command requires redirect_text")
        if self.activity_command != "redirect" and self.redirect_text is not None:
            raise ValueError("redirect_text requires redirect activity command")
        if self.activity_command == "reassign" and self.replacement_executor_id is None:
            raise ValueError("reassign activity command requires replacement_executor_id")
        if self.activity_command != "reassign" and self.replacement_executor_id is not None:
            raise ValueError("replacement_executor_id requires reassign activity command")
        return self

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


class EntityStatusPrecondition(_SettlementContract):
    entity_id: EntityId
    status: Literal["active", "inactive", "ended"]


class EntityTransitionWorldDelta(_SettlementContract):
    delta_type: Literal["entity_transition"] = "entity_transition"
    delta_id: DeltaId
    operation: Literal["replace", "split", "merge"]
    sources: list[EntityStatusPrecondition] = Field(min_length=1)
    result_entities: list[WorldEntity] = Field(min_length=1)
    ended_at: str | None = None
    source_proposal: str | None = None

    @model_validator(mode="after")
    def _validate_transition_shape(self) -> EntityTransitionWorldDelta:
        source_ids = [source.entity_id for source in self.sources]
        result_ids = [entity.entity_id for entity in self.result_entities]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("entity transition sources must be unique")
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("entity transition results must be unique")
        if set(source_ids) & set(result_ids):
            raise ValueError("entity transition results require new stable entity IDs")
        expected_shape = {
            "replace": (len(source_ids) == 1 and len(result_ids) == 1),
            "split": (len(source_ids) == 1 and len(result_ids) >= 2),
            "merge": (len(source_ids) >= 2 and len(result_ids) == 1),
        }
        if not expected_shape[self.operation]:
            raise ValueError(f"invalid {self.operation} entity transition cardinality")
        if any(entity.status == "ended" for entity in self.result_entities):
            raise ValueError("entity transition cannot create an already-ended result")
        return self


class RelationshipWorldDelta(_SettlementContract):
    delta_type: Literal["relationship"] = "relationship"
    delta_id: DeltaId
    operation: Literal["create", "update", "end", "grant", "revoke", "assign"]
    relationship_id: RelationId | None = None
    from_entity_id: EntityId
    to_entity_id: EntityId
    relationship_type: str = Field(min_length=1)
    before_status: Literal["active", "ended"] | None = None
    next_status: Literal["active", "ended"] | None = None
    source_proposal: str | None = None


class PermissionWorldDelta(_SettlementContract):
    delta_type: Literal["permission"] = "permission"
    delta_id: DeltaId
    operation: Literal["grant", "revoke"]
    target_entity_id: EntityId
    permission_id: PermissionId
    permission: PermissionReference | None = None
    before_permission: PermissionReference | None = None
    source_proposal: str | None = None

    @model_validator(mode="after")
    def _validate_permission_shape(self) -> PermissionWorldDelta:
        if self.operation == "grant":
            if (
                self.permission is None
                or self.permission.permission_id != self.permission_id
                or self.before_permission is not None
            ):
                raise ValueError("permission grant requires one matching typed permission")
        elif (
            self.permission is not None
            or self.before_permission is None
            or self.before_permission.permission_id != self.permission_id
        ):
            raise ValueError("permission revoke requires the matching prior permission")
        return self


class OfficeWorldDelta(_SettlementContract):
    delta_type: Literal["office"] = "office"
    delta_id: DeltaId
    operation: Literal["assign", "vacate"]
    office_entity_id: EntityId
    before_holder_entity_id: EntityId | None
    holder_entity_id: EntityId | None = None
    source_proposal: str | None = None

    @model_validator(mode="after")
    def _validate_office_shape(self) -> OfficeWorldDelta:
        if self.operation == "assign":
            if self.holder_entity_id is None:
                raise ValueError("office assignment requires holder_entity_id")
            if self.holder_entity_id == self.before_holder_entity_id:
                raise ValueError("office assignment must change its holder")
        elif self.holder_entity_id is not None or self.before_holder_entity_id is None:
            raise ValueError("office vacancy requires the prior holder and no next holder")
        return self


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
    operation: Literal["identity", "freedom", "location", "regime", "death"]
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
    before_status: Literal["active", "ended"] | None = None
    record: ModifierRecord | None = None
    ended_at: WorldInstant | None = None
    source_proposal: str | None = None

    @model_validator(mode="after")
    def _validate_record(self) -> ModifierWorldDelta:
        if self.operation in {"create", "update"}:
            if (
                self.record is None
                or self.record.modifier_id != self.modifier_id
                or self.ended_at is not None
            ):
                raise ValueError("create/update modifier delta requires a matching typed record")
        elif self.record is not None or self.ended_at is None:
            raise ValueError("end modifier delta requires ended_at and cannot replace its record")
        return self


class CommitmentWorldDelta(_SettlementContract):
    delta_type: Literal["commitment"] = "commitment"
    delta_id: DeltaId
    operation: Literal["create", "update", "apply", "cancel", "fail"]
    commitment_id: str
    before_status: Literal["pending", "applied", "cancelled", "failed"] | None = None
    record: CommitmentRecord | None = None
    transitioned_at: WorldInstant | None = None
    source_proposal: str | None = None

    @model_validator(mode="after")
    def _validate_record(self) -> "CommitmentWorldDelta":
        if self.operation in {"create", "update"}:
            if (
                self.record is None
                or self.record.commitment_id != self.commitment_id
                or self.transitioned_at is not None
            ):
                raise ValueError("create/update commitment delta requires a matching typed record")
        elif self.record is not None or self.transitioned_at is None:
            raise ValueError("commitment transition requires transitioned_at and cannot replace its record")
        return self


class ElapsedStatePatchDelta(_SettlementContract):
    """Typed compatibility output from an elapsed-time gameplay handler.

    The patch is restricted and validated by ``engine.settlement``. It exists so
    legacy monthly gameplay math can participate in the pure clock-consumer
    contract without letting ``engine.clock`` own that math.
    """

    delta_type: Literal["elapsed_state_patch"] = "elapsed_state_patch"
    delta_id: DeltaId
    handler_name: str = Field(min_length=1)
    handler_version: str = Field(min_length=1)
    boundary_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    before_fields: dict[str, object]
    after_fields: dict[str, object]
    source_proposal: str | None = None


class CompatibilityStatePatchDelta(_SettlementContract):
    """Allowlisted state difference produced by an isolated legacy action adapter.

    This temporary bridge lets mature decree/TRPG rules participate in the
    versioned settlement protocol without granting them access to the clock,
    world identity, entity registry, player identity, or activity graph.
    """

    delta_type: Literal["compatibility_state_patch"] = "compatibility_state_patch"
    delta_id: DeltaId
    adapter_name: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    before_fields: dict[str, object]
    after_fields: dict[str, object]
    source_proposal: str | None = None


WorldDelta = Annotated[
    MetricWorldDelta
    | EntityWorldDelta
    | EntityTransitionWorldDelta
    | RelationshipWorldDelta
    | PermissionWorldDelta
    | OfficeWorldDelta
    | LifecycleWorldDelta
    | PlayerWorldDelta
    | ModifierWorldDelta
    | CommitmentWorldDelta
    | ElapsedStatePatchDelta
    | CompatibilityStatePatchDelta,
    Field(discriminator="delta_type"),
]


class ProviderAttribution(_SettlementContract):
    provider: str | None = None
    provider_type: str | None = None
    model: str | None = None
    request_id: str | None = None


class ActivityCandidate(_SettlementContract):
    kind: str = Field(min_length=1, max_length=120)
    target_summary: str | None = Field(default=None, max_length=1000)
    prerequisites: list[str] = Field(default_factory=list)
    planned_effects: list[str] = Field(default_factory=list)
    checkpoint_horizon_hours: int = Field(default=720, strict=True, ge=1, le=2160)


class ActivityCheckpointDecision(_SettlementContract):
    transition: Literal[
        "continue",
        "pause",
        "redirect",
        "fail",
        "complete",
        "await_player",
    ]
    reason: str = Field(min_length=1, max_length=1000)
    remaining_duration: Duration | None = None
    interruption_facts: list[str] = Field(default_factory=list)
    pending_decision: PendingActivityDecision | None = None

    @model_validator(mode="after")
    def _validate_transition(self) -> ActivityCheckpointDecision:
        if self.transition == "await_player" and self.pending_decision is None:
            raise ValueError("await_player transition requires a pending decision")
        if self.transition != "await_player" and self.pending_decision is not None:
            raise ValueError("pending decision requires await_player transition")
        if self.transition in {"fail", "complete"} and self.remaining_duration is not None:
            raise ValueError("terminal checkpoint transition cannot retain duration")
        return self


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
    duration_candidate: Duration | None = None
    duration_reason: str | None = Field(default=None, max_length=1000)
    activity_candidate: ActivityCandidate | None = None
    activity_decision: ActivityCheckpointDecision | None = None
    uncertainty: float | None = Field(default=None, ge=0, le=1)
    deltas: list[WorldDelta] = Field(default_factory=list)
    provider: ProviderAttribution = Field(default_factory=ProviderAttribution)

    @model_validator(mode="after")
    def _validate_duration_reason_pair(self) -> AdjudicationProposal:
        if self.duration_candidate is not None:
            if self.duration_reason is None or not self.duration_reason.strip():
                raise ValueError("duration_candidate requires a nonblank duration_reason")
        elif self.duration_reason is not None:
            raise ValueError("duration_reason requires duration_candidate")
        if self.activity_candidate is not None and self.duration_candidate is None:
            raise ValueError("activity_candidate requires a planned duration")
        return self


class SettlementAttribution(_SettlementContract):
    requested_executor_id: EntityId | None = None
    actual_executor_id: EntityId | None = None
    execution_status: str
    provider: ProviderAttribution
    executor_facts: ExecutorFacts | None = None


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
    regional_targets: list[str] = Field(default_factory=list)
    target_region_ids: list[EntityId] = Field(default_factory=list)
    target_entity_ids: list[EntityId] = Field(default_factory=list)
    deltas: list[WorldDelta] = Field(default_factory=list)
    duration_reason: str | None = None
    time_plan: ElapsedSegmentPlan | None = None
    activity_id: ActivityId | None = None
    checkpoint_id: CheckpointId | None = None
    checkpoint_sequence: int | None = Field(default=None, strict=True, ge=1)
    activity_status: str | None = None
    crossed_events: list[str] = Field(default_factory=list)
    actual_outcome: str | None = None
    attribution: SettlementAttribution
    world_state_attribution: list[AppliedMetricAttribution] = Field(default_factory=list)
    rolls: list[RollRecord] = Field(default_factory=list)
    committed_at: datetime


class TerminalRecordFacts(_SettlementContract):
    schema_version: Literal[1] = 1
    terminal_record_id: TerminalRecordId
    game_id: GameId
    branch_id: BranchId
    settlement_id: SettlementId
    previous_version_id: VersionId
    version_id: VersionId
    trigger_action: ClientActionId
    direct_cause: str = Field(min_length=1, max_length=1000)
    key_factors: list[str] = Field(min_length=1)
    causal_summary: str = Field(min_length=1, max_length=2000)
    final_life_status: Literal["dead"] = "dead"
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
