from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, NewType
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


WORLD_SCHEMA_VERSION = 1
DEFAULT_CALENDAR_SCHEMA_VERSION = "yuanming-calendar-v1"
ASSEMBLY_PARTICIPATE_CAPABILITY = "governance.assembly.participate"
ENTITY_DIALOGUE_CAPABILITY = "narrative.entity.dialogue"
MEMORIAL_SUBMIT_CAPABILITY = "governance.memorial.submit"
OFFICE_APPOINTABLE_CAPABILITY = "governance.office.appointable"

GameId = NewType("GameId", UUID)
BranchId = NewType("BranchId", UUID)
VersionId = NewType("VersionId", UUID)
SettlementId = NewType("SettlementId", UUID)
ClientActionId = NewType("ClientActionId", UUID)
EntityId = NewType("EntityId", UUID)
RelationId = NewType("RelationId", UUID)
PermissionId = NewType("PermissionId", UUID)
DeltaId = NewType("DeltaId", UUID)
BookmarkId = NewType("BookmarkId", UUID)
TerminalRecordId = NewType("TerminalRecordId", UUID)
ActivityId = NewType("ActivityId", UUID)
CheckpointId = NewType("CheckpointId", UUID)


def new_game_id() -> GameId:
    return GameId(uuid4())


def new_branch_id() -> BranchId:
    return BranchId(uuid4())


def new_version_id() -> VersionId:
    return VersionId(uuid4())


def new_settlement_id() -> SettlementId:
    return SettlementId(uuid4())


def new_client_action_id() -> ClientActionId:
    return ClientActionId(uuid4())


def new_entity_id() -> EntityId:
    return EntityId(uuid4())


def new_relation_id() -> RelationId:
    return RelationId(uuid4())


def new_permission_id() -> PermissionId:
    return PermissionId(uuid4())


def new_delta_id() -> DeltaId:
    return DeltaId(uuid4())


def new_terminal_record_id() -> TerminalRecordId:
    return TerminalRecordId(uuid4())


def new_activity_id() -> ActivityId:
    return ActivityId(uuid4())


def new_checkpoint_id() -> CheckpointId:
    return CheckpointId(uuid4())


class _WorldContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ImmutableWorldContract(_WorldContract):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorldInstant(_WorldContract):
    absolute_hour: int = Field(strict=True, ge=0)
    calendar_version: str = DEFAULT_CALENDAR_SCHEMA_VERSION
    epoch_id: str = "yuanming-1328-10-01-zishi"
    world_timezone: str = "UTC+08:00"


class WorldClock(WorldInstant):
    """Canonical persisted world clock; projections are always derived."""


class CalendarProjection(_WorldContract):
    absolute_hour: int = Field(strict=True, ge=0)
    calendar_version: str = DEFAULT_CALENDAR_SCHEMA_VERSION
    year: int = Field(strict=True)
    month: int = Field(strict=True, ge=1, le=12)
    is_leap_month: bool = False
    month_length: Literal[29, 30]
    day: int = Field(strict=True, ge=1, le=30)
    hour: int = Field(strict=True, ge=0, le=23)
    double_hour_index: int = Field(strict=True, ge=0, le=11)
    double_hour_name: str
    solar_term: str
    era_name: str
    era_year: int = Field(strict=True)

    @model_validator(mode="after")
    def _validate_day_in_month(self) -> CalendarProjection:
        if self.day > self.month_length:
            raise ValueError("day exceeds month length")
        return self


class Duration(_WorldContract):
    unit: Literal["hour", "day", "month", "year"]
    value: int = Field(strict=True, gt=0)


class NormalizedDuration(_WorldContract):
    duration: Duration
    start: WorldInstant
    end: WorldInstant
    elapsed_hours: int = Field(strict=True, gt=0)
    start_calendar: CalendarProjection
    end_calendar: CalendarProjection


BoundaryKind = Literal["day", "month", "year", "solar_term", "end"]


class TimeBoundary(_ImmutableWorldContract):
    boundary_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: BoundaryKind
    boundary_key: str = Field(min_length=1)
    absolute_hour: int = Field(strict=True, ge=0)
    calendar_version: str = DEFAULT_CALENDAR_SCHEMA_VERSION
    epoch_id: str = "yuanming-1328-10-01-zishi"
    world_timezone: str = "UTC+08:00"
    projection: CalendarProjection

    @model_validator(mode="after")
    def _validate_projection_identity(self) -> TimeBoundary:
        if self.projection.absolute_hour != self.absolute_hour:
            raise ValueError("boundary projection absolute_hour mismatch")
        if self.projection.calendar_version != self.calendar_version:
            raise ValueError("boundary projection calendar_version mismatch")
        return self


class ElapsedSegment(_ImmutableWorldContract):
    segment_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_action_id: ClientActionId
    start: WorldInstant
    end: WorldInstant
    elapsed_hours: int = Field(strict=True, gt=0)

    @model_validator(mode="after")
    def _validate_interval(self) -> ElapsedSegment:
        if (
            self.start.calendar_version != self.end.calendar_version
            or self.start.epoch_id != self.end.epoch_id
            or self.start.world_timezone != self.end.world_timezone
        ):
            raise ValueError("elapsed segment clock identities do not match")
        if self.end.absolute_hour <= self.start.absolute_hour:
            raise ValueError("elapsed segment end must be after start")
        if self.elapsed_hours != self.end.absolute_hour - self.start.absolute_hour:
            raise ValueError("elapsed segment elapsed_hours mismatch")
        return self


class ClockConsumerInvocation(_ImmutableWorldContract):
    invocation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    consumer_name: str = Field(min_length=1)
    consumer_version: str = Field(min_length=1)
    consumer_order: int = Field(strict=True)
    segment_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    boundary_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    boundary_kind: BoundaryKind
    ordinal: int = Field(strict=True, ge=0)


class ElapsedSegmentPlan(_ImmutableWorldContract):
    normalized_duration: NormalizedDuration
    segment: ElapsedSegment
    boundaries: tuple[TimeBoundary, ...]
    consumer_invocations: tuple[ClockConsumerInvocation, ...] = ()

    @model_validator(mode="after")
    def _validate_plan_links(self) -> ElapsedSegmentPlan:
        normalized = self.normalized_duration
        if (
            normalized.start != self.segment.start
            or normalized.end != self.segment.end
            or normalized.elapsed_hours != self.segment.elapsed_hours
        ):
            raise ValueError("normalized duration does not match elapsed segment")

        boundary_by_id = {
            boundary.boundary_id: boundary for boundary in self.boundaries
        }
        boundary_ids = set(boundary_by_id)
        if len(boundary_ids) != len(self.boundaries):
            raise ValueError("elapsed segment plan contains duplicate boundary ids")
        if not any(
            boundary.kind == "end"
            and boundary.absolute_hour == self.segment.end.absolute_hour
            for boundary in self.boundaries
        ):
            raise ValueError("elapsed segment plan requires its terminal end boundary")
        for boundary in self.boundaries:
            if (
                boundary.calendar_version != self.segment.start.calendar_version
                or boundary.epoch_id != self.segment.start.epoch_id
                or boundary.world_timezone != self.segment.start.world_timezone
            ):
                raise ValueError("boundary clock identity does not match its segment")
            if not (
                self.segment.start.absolute_hour
                < boundary.absolute_hour
                <= self.segment.end.absolute_hour
            ):
                raise ValueError("boundary lies outside the elapsed segment")

        invocation_ids = {
            invocation.invocation_id for invocation in self.consumer_invocations
        }
        if len(invocation_ids) != len(self.consumer_invocations):
            raise ValueError("elapsed segment plan contains duplicate invocation ids")
        if [
            invocation.ordinal for invocation in self.consumer_invocations
        ] != list(range(len(self.consumer_invocations))):
            raise ValueError("consumer invocation ordinals must be contiguous and ordered")
        for invocation in self.consumer_invocations:
            if invocation.segment_id != self.segment.segment_id:
                raise ValueError("consumer invocation references another segment")
            if invocation.boundary_id not in boundary_ids:
                raise ValueError("consumer invocation references an unknown boundary")
            if (
                invocation.boundary_kind
                != boundary_by_id[invocation.boundary_id].kind
            ):
                raise ValueError("consumer invocation boundary kind mismatch")
        return self


ActivityStatus = Literal[
    "in_progress",
    "awaiting_player_decision",
    "paused",
    "cancelled",
    "failed",
    "completed",
]
CheckpointStatus = Literal["pending", "completed"]


class PendingActivityDecision(_WorldContract):
    decision_type: Literal["continue", "redirect", "reassign", "stop"]
    reason: str = Field(min_length=1, max_length=1000)
    options: list[str] = Field(default_factory=list, min_length=1)
    facts: list[str] = Field(default_factory=list)


class ActivityCheckpoint(_WorldContract):
    checkpoint_id: CheckpointId
    activity_id: ActivityId
    sequence: int = Field(strict=True, ge=1)
    client_action_id: ClientActionId
    expected_parent_version_id: VersionId
    planned_start: WorldInstant
    planned_end: WorldInstant
    status: CheckpointStatus = "pending"
    settlement_id: SettlementId | None = None
    version_id: VersionId | None = None
    crossed_boundary_ids: list[str] = Field(default_factory=list)
    committed_delta_ids: list[DeltaId] = Field(default_factory=list)
    interruption_facts: list[str] = Field(default_factory=list)
    roll_key: str | None = None
    roll_value: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def _validate_checkpoint(self) -> ActivityCheckpoint:
        if self.planned_end.absolute_hour <= self.planned_start.absolute_hour:
            raise ValueError("activity checkpoint end must be after start")
        if (
            self.planned_start.calendar_version != self.planned_end.calendar_version
            or self.planned_start.epoch_id != self.planned_end.epoch_id
            or self.planned_start.world_timezone != self.planned_end.world_timezone
        ):
            raise ValueError("activity checkpoint clock identities do not match")
        if self.status == "pending" and (
            self.settlement_id is not None or self.version_id is not None
        ):
            raise ValueError("pending activity checkpoint cannot reference a commit")
        if self.status == "completed" and (
            self.settlement_id is None or self.version_id is None
        ):
            raise ValueError("completed activity checkpoint requires settlement/version")
        if (self.roll_key is None) != (self.roll_value is None):
            raise ValueError("activity checkpoint roll key/value must be paired")
        return self


class Activity(_WorldContract):
    activity_id: ActivityId
    kind: str = Field(min_length=1, max_length=120)
    status: ActivityStatus = "in_progress"
    intent: str = Field(min_length=1, max_length=4000)
    target_summary: str | None = Field(default=None, max_length=1000)
    requested_executor_id: EntityId | None = None
    actual_executor_id: EntityId | None = None
    started_at: WorldInstant
    planned_duration: Duration
    planned_end: WorldInstant
    planned_elapsed_hours: int = Field(strict=True, gt=0)
    elapsed_hours: int = Field(default=0, strict=True, ge=0)
    remaining_hours: int = Field(strict=True, ge=0)
    checkpoint_horizon_hours: int = Field(default=720, strict=True, ge=1, le=2160)
    next_checkpoint_id: CheckpointId | None = None
    checkpoint_sequence: int = Field(default=1, strict=True, ge=1)
    prerequisites: list[str] = Field(default_factory=list)
    planned_effects: list[str] = Field(default_factory=list)
    committed_segment_effects: list[str] = Field(default_factory=list)
    interruption_facts: list[str] = Field(default_factory=list)
    pending_decision: PendingActivityDecision | None = None
    checkpoints: list[ActivityCheckpoint] = Field(default_factory=list)
    created_by_action_id: ClientActionId

    @model_validator(mode="after")
    def _validate_activity(self) -> Activity:
        if self.planned_end.absolute_hour <= self.started_at.absolute_hour:
            raise ValueError("activity planned end must be after start")
        if self.planned_elapsed_hours != (
            self.planned_end.absolute_hour - self.started_at.absolute_hour
        ):
            raise ValueError("activity planned elapsed hours mismatch")
        if self.elapsed_hours + self.remaining_hours > self.planned_elapsed_hours:
            raise ValueError("activity elapsed/remaining hours exceed its plan")
        sequences = [checkpoint.sequence for checkpoint in self.checkpoints]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("activity checkpoint sequences must be contiguous")
        if any(
            checkpoint.activity_id != self.activity_id
            for checkpoint in self.checkpoints
        ):
            raise ValueError("activity contains a checkpoint owned by another activity")
        pending = [
            checkpoint
            for checkpoint in self.checkpoints
            if checkpoint.status == "pending"
        ]
        if self.status in {"in_progress", "awaiting_player_decision", "paused"}:
            if len(pending) != 1 or pending[0].checkpoint_id != self.next_checkpoint_id:
                raise ValueError("active activity requires exactly one next checkpoint")
        elif pending or self.next_checkpoint_id is not None:
            raise ValueError("terminal activity cannot retain a pending checkpoint")
        if self.status == "awaiting_player_decision" and self.pending_decision is None:
            raise ValueError("awaiting activity requires a pending player decision")
        if self.status != "awaiting_player_decision" and self.pending_decision is not None:
            raise ValueError("only awaiting activity may retain a pending player decision")
        return self


class WorldSnapshotMetadata(_WorldContract):
    """Version identity embedded in a recoverable state snapshot.

    The database graph remains authoritative. These fields let a decoded
    snapshot explain where it came from without relying on process-local state.
    """

    schema_version: Literal[1] = WORLD_SCHEMA_VERSION
    calendar_schema_version: str = DEFAULT_CALENDAR_SCHEMA_VERSION
    game_id: GameId | None = None
    branch_id: BranchId | None = None
    version_id: VersionId | None = None
    source_kind: Literal["initial", "legacy_save", "settlement", "fork"] = "initial"
    source_ref: str | None = None
    imported_at: datetime | None = None
    migration_notes: list[str] = Field(default_factory=list)


class EntitySource(_WorldContract):
    kind: Literal["initial_data", "legacy_save", "adjudication", "system"]
    reference: str | None = None
    summary: str = ""


class PermissionReference(_WorldContract):
    permission_id: PermissionId
    capability: str = Field(min_length=1)
    scope_entity_id: EntityId | None = None
    granted_by_entity_id: EntityId | None = None


class RelationshipEdge(_WorldContract):
    relationship_id: RelationId
    relationship_type: str = Field(min_length=1)
    from_entity_id: EntityId
    to_entity_id: EntityId
    status: Literal["active", "ended"] = "active"


class WorldEntityBase(_WorldContract):
    entity_id: EntityId
    display_name: str = Field(min_length=1)
    status: Literal["active", "inactive", "ended"] = "active"
    created_by_settlement_id: SettlementId | None = None
    origin_version_id: VersionId | None = None
    active_from: str | None = None
    ended_at: str | None = None
    source: EntitySource
    permissions: list[PermissionReference] = Field(default_factory=list)
    relationships: list[RelationshipEdge] = Field(default_factory=list)
    knowledge_boundaries: list[str] = Field(default_factory=list)
    available: bool = True


class PersonEntity(WorldEntityBase):
    entity_type: Literal["person"] = "person"
    legacy_name: str | None = None
    faction_ids: list[EntityId] = Field(default_factory=list)
    office_ids: list[EntityId] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)


class FactionEntity(WorldEntityBase):
    entity_type: Literal["faction"] = "faction"
    member_ids: list[EntityId] = Field(default_factory=list)
    influence: int | None = None


class InstitutionEntity(WorldEntityBase):
    entity_type: Literal["institution"] = "institution"
    institution_kind: str
    member_ids: list[EntityId] = Field(default_factory=list)


class OfficeEntity(WorldEntityBase):
    entity_type: Literal["office"] = "office"
    holder_entity_id: EntityId | None = None
    responsibility: str = ""


class TemporaryAuthorityEntity(WorldEntityBase):
    entity_type: Literal["temporary_authority"] = "temporary_authority"
    represented_entity_ids: list[EntityId] = Field(default_factory=list)
    expires_on: str | None = None


class RegionEntity(WorldEntityBase):
    entity_type: Literal["region"] = "region"
    legacy_name: str | None = None
    controller_entity_id: EntityId | None = None


WorldEntity = Annotated[
    PersonEntity
    | FactionEntity
    | InstitutionEntity
    | OfficeEntity
    | TemporaryAuthorityEntity
    | RegionEntity,
    Field(discriminator="entity_type"),
]


def validate_entity_registry(
    registry: Mapping[EntityId, WorldEntity],
) -> None:
    """Validate cross-entity references and globally stable registry identities."""

    known_ids = set(registry)
    relationship_ids: set[RelationId] = set()
    permission_ids: set[PermissionId] = set()
    relationship_keys: set[tuple[EntityId, EntityId, str]] = set()

    for registry_id, entity in registry.items():
        if registry_id != entity.entity_id:
            raise ValueError("registry key does not match embedded entity_id")
        if entity.status == "ended" and entity.available:
            raise ValueError("ended registry entity cannot remain available")

        for permission in entity.permissions:
            if permission.permission_id in permission_ids:
                raise ValueError("permission_id must be globally unique")
            permission_ids.add(permission.permission_id)
            for reference in (
                permission.scope_entity_id,
                permission.granted_by_entity_id,
            ):
                if reference is not None and reference not in known_ids:
                    raise ValueError("permission references an unknown entity")
            if (
                entity.status != "ended"
                and permission.scope_entity_id is not None
                and registry[permission.scope_entity_id].status == "ended"
            ):
                raise ValueError("active permission cannot target an ended scope entity")

        for relationship in entity.relationships:
            if relationship.relationship_id in relationship_ids:
                raise ValueError("relationship_id must be globally unique")
            relationship_ids.add(relationship.relationship_id)
            relationship_key = (
                relationship.from_entity_id,
                relationship.to_entity_id,
                relationship.relationship_type,
            )
            if relationship_key in relationship_keys:
                raise ValueError("registry contains a duplicate relationship edge")
            relationship_keys.add(relationship_key)
            if relationship.from_entity_id != entity.entity_id:
                raise ValueError("relationship owner does not match from_entity_id")
            if relationship.to_entity_id not in known_ids:
                raise ValueError("relationship references an unknown entity")
            if relationship.from_entity_id == relationship.to_entity_id:
                raise ValueError("relationship cannot reference the same entity twice")
            if (
                entity.status != "ended"
                and relationship.status == "active"
                and registry[relationship.to_entity_id].status == "ended"
            ):
                raise ValueError("active relationship cannot target an ended entity")

        for field in (
            "faction_ids",
            "office_ids",
            "member_ids",
            "represented_entity_ids",
        ):
            references = list(getattr(entity, field, []))
            if len(references) != len(set(references)):
                raise ValueError(f"{field} contains duplicate entity references")
            if entity.entity_id in references:
                raise ValueError(f"{field} cannot reference the entity itself")
            if any(reference not in known_ids for reference in references):
                raise ValueError(f"{field} references an unknown entity")
            if entity.status != "ended" and any(
                registry[reference].status == "ended" for reference in references
            ):
                raise ValueError(f"{field} cannot reference an ended entity")
        for field in ("holder_entity_id", "controller_entity_id"):
            reference = getattr(entity, field, None)
            if reference == entity.entity_id:
                raise ValueError(f"{field} cannot reference the entity itself")
            if reference is not None and reference not in known_ids:
                raise ValueError(f"{field} references an unknown entity")
            if (
                entity.status != "ended"
                and reference is not None
                and registry[reference].status == "ended"
            ):
                raise ValueError(f"{field} cannot reference an ended entity")

    for entity in registry.values():
        if isinstance(entity, PersonEntity):
            for office_id in entity.office_ids:
                office = registry[office_id]
                if not isinstance(office, OfficeEntity):
                    raise ValueError("person office_ids must reference OfficeEntity records")
                if office.holder_entity_id != entity.entity_id:
                    raise ValueError("person office_ids and office holder disagree")
        if isinstance(entity, OfficeEntity) and entity.holder_entity_id is not None:
            holder = registry[entity.holder_entity_id]
            if isinstance(holder, PersonEntity) and entity.entity_id not in holder.office_ids:
                raise ValueError("office holder and person office_ids disagree")


class PlayerWorldStatus(_WorldContract):
    player_character_id: EntityId | None = None
    life_status: Literal["alive", "dead"] = "alive"
    identity_summary: str = ""
    controlled_faction_id: EntityId | None = None
    location_entity_id: EntityId | None = None
    freedom_status: Literal["free", "detained", "exiled", "hidden"] = "free"
    regime_status: Literal["governing", "overthrown", "regime_destroyed"] = "governing"
    actionable_goal_ids: list[str] = Field(default_factory=list)
    terminal_settlement_id: SettlementId | None = None
    terminal_version_id: VersionId | None = None

    @model_validator(mode="after")
    def _validate_terminal_identity(self) -> PlayerWorldStatus:
        terminal_ids_are_paired = (
            self.terminal_settlement_id is None
        ) == (self.terminal_version_id is None)
        if not terminal_ids_are_paired:
            raise ValueError("terminal settlement/version ids must be paired")
        if self.life_status == "dead" and self.terminal_settlement_id is None:
            raise ValueError("dead player status requires committed terminal ids")
        if self.life_status == "alive" and self.terminal_settlement_id is not None:
            raise ValueError("alive player status cannot retain terminal ids")
        return self


class WorldBranchRef(_WorldContract):
    game_id: GameId
    branch_id: BranchId
    parent_branch_id: BranchId | None = None
    forked_from_version_id: VersionId | None = None
    head_version_id: VersionId
    created_at: datetime
    status: Literal["active", "archived"] = "active"


class WorldVersionRef(_WorldContract):
    game_id: GameId
    branch_id: BranchId
    version_id: VersionId
    parent_version_id: VersionId | None = None
    settlement_id: SettlementId | None = None
    created_at: datetime
    protected: bool = False
