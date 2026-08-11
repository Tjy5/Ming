"""Typed contracts for deterministic world-state calculation and projections."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .world import EntityId, VersionId, WorldInstant


MetricScope = Literal["world", "region", "entity"]
UncertaintyReason = Literal[
    "opposition",
    "hidden_information",
    "hazard",
    "volatile_environment",
]


class _WorldStateContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricTarget(_WorldStateContract):
    target_scope: MetricScope
    metric_key: str = Field(min_length=1)
    target_entity_id: EntityId | None = None

    @model_validator(mode="after")
    def _validate_target(self) -> "MetricTarget":
        if self.target_scope == "world" and self.target_entity_id is not None:
            raise ValueError("world metric targets cannot carry an entity id")
        if self.target_scope != "world" and self.target_entity_id is None:
            raise ValueError("entity-scoped metric targets require an entity id")
        return self


class MetricSpec(_WorldStateContract):
    target_scope: MetricScope
    metric_key: str = Field(min_length=1)
    numeric_kind: Literal["integer", "decimal"]
    precision: int = Field(default=0, ge=0, le=6)
    minimum: Decimal | None = None
    maximum: Decimal | None = None

    @model_validator(mode="after")
    def _validate_bounds(self) -> "MetricSpec":
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("metric minimum cannot exceed maximum")
        if self.numeric_kind == "integer" and self.precision != 0:
            raise ValueError("integer metrics must use zero decimal precision")
        return self


class ExecutorFactor(_WorldStateContract):
    name: str = Field(min_length=1)
    value: Decimal
    source: str = Field(min_length=1)


class ExecutorFacts(_WorldStateContract):
    requested_executor_id: EntityId | None = None
    actual_executor_id: EntityId | None = None
    selection_source: Literal["player", "ai", "none"] = "none"
    execution_status: str
    entity_type: str | None = None
    display_name: str | None = None
    version_id: VersionId | None = None
    factors: list[ExecutorFactor] = Field(default_factory=list)
    efficiency: Decimal = Field(default=Decimal("1"), ge=0, le=1)


class VisibleRollModifier(_WorldStateContract):
    name: str = Field(min_length=1)
    value: int = Field(strict=True)
    source_fact: str = Field(min_length=1)


class RollRecord(_WorldStateContract):
    roll_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_version: str = Field(min_length=1)
    raw_d100: int = Field(strict=True, ge=1, le=100)
    modifiers: list[VisibleRollModifier] = Field(default_factory=list)
    uncertainty_reasons: list[UncertaintyReason] = Field(min_length=1)
    fact_references: list[str] = Field(min_length=1)
    checkpoint_slot: str = Field(min_length=1)


class AppliedMetricAttribution(_WorldStateContract):
    delta_id: str = Field(min_length=1)
    target: MetricTarget
    before_value: int | float
    proposed_value: int | float
    executor_adjustment: int | float = 0
    precision_adjustment: int | float = 0
    clamp_adjustment: int | float = 0
    actual_delta: int | float
    after_value: int | float
    executor_facts: ExecutorFacts | None = None
    roll_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ModifierTransform(_WorldStateContract):
    kind: Literal["add", "multiply", "minimum", "maximum"]
    amount: Decimal | None = None
    numerator: int | None = Field(default=None, strict=True)
    denominator: int | None = Field(default=None, strict=True, gt=0)

    @model_validator(mode="after")
    def _validate_transform(self) -> "ModifierTransform":
        if self.kind == "multiply":
            if self.numerator is None or self.denominator is None or self.amount is not None:
                raise ValueError("multiply transforms require numerator/denominator only")
        elif self.amount is None or self.numerator is not None or self.denominator is not None:
            raise ValueError("non-multiply transforms require amount only")
        return self


class ModifierRecord(_WorldStateContract):
    modifier_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    target: MetricTarget
    source_kind: Literal["settlement", "event", "policy", "activity", "system"]
    source_ref: str = Field(min_length=1)
    transform: ModifierTransform
    started_at: WorldInstant
    ends_at: WorldInstant | None = None
    invalidation_condition: str | None = Field(default=None, min_length=1)
    stacking_group: str = Field(min_length=1)
    stacking_policy: Literal["stack", "replace", "exclusive"] = "stack"
    priority: int = Field(default=0, strict=True)
    status: Literal["active", "ended"] = "active"
    ended_at: WorldInstant | None = None

    @model_validator(mode="after")
    def _validate_lifecycle(self) -> "ModifierRecord":
        if self.ends_at is None and self.invalidation_condition is None:
            raise ValueError("modifier requires ends_at or a typed invalidation condition")
        if self.ends_at is not None:
            if self.ends_at.absolute_hour <= self.started_at.absolute_hour:
                raise ValueError("modifier ends_at must be after started_at")
            if (
                self.ends_at.calendar_version != self.started_at.calendar_version
                or self.ends_at.epoch_id != self.started_at.epoch_id
                or self.ends_at.world_timezone != self.started_at.world_timezone
            ):
                raise ValueError("modifier clock identities do not match")
        if self.status == "active" and self.ended_at is not None:
            raise ValueError("active modifier cannot have ended_at")
        if self.status == "ended" and self.ended_at is None:
            raise ValueError("ended modifier requires ended_at")
        return self


class CommitmentRecord(_WorldStateContract):
    commitment_id: str = Field(min_length=1)
    target: MetricTarget
    amount: Decimal
    source_kind: Literal["policy", "mission", "activity", "event"]
    source_ref: str = Field(min_length=1)
    due_at: WorldInstant
    status: Literal["pending", "applied", "cancelled", "failed"] = "pending"

    @model_validator(mode="after")
    def _validate_amount(self) -> "CommitmentRecord":
        if not self.amount.is_finite() or self.amount == 0:
            raise ValueError("commitment amount must be finite and non-zero")
        return self


class WorldStateLedger(_WorldStateContract):
    modifiers: dict[str, ModifierRecord] = Field(default_factory=dict)
    commitments: dict[str, CommitmentRecord] = Field(default_factory=dict)


class MetricProjection(_WorldStateContract):
    version_id: VersionId | None = None
    target: MetricTarget
    base_value: int | float
    base_band: str | None = None
    active_modifiers: list[ModifierRecord] = Field(default_factory=list)
    effective_value: int | float
    effective_band: str | None = None
    recent_sources: list[AppliedMetricAttribution] = Field(default_factory=list)
    commitments: list[CommitmentRecord] = Field(default_factory=list)


class ExecutorCandidateProjection(_WorldStateContract):
    version_id: VersionId | None = None
    executor: ExecutorFacts
    available: bool
    authority: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class RegionProjection(_WorldStateContract):
    version_id: VersionId | None = None
    region_id: EntityId
    display_name: str
    controller_entity_id: EntityId | None = None
    local_entity_ids: list[EntityId] = Field(default_factory=list)
    metrics: list[MetricProjection] = Field(default_factory=list)


class WorldStateProjection(_WorldStateContract):
    version_id: VersionId | None = None
    metrics: list[MetricProjection] = Field(default_factory=list)
    executors: list[ExecutorCandidateProjection] = Field(default_factory=list)
    regions: list[RegionProjection] = Field(default_factory=list)
