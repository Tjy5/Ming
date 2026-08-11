from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, NewType
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


WORLD_SCHEMA_VERSION = 1
DEFAULT_CALENDAR_SCHEMA_VERSION = "yuanming-calendar-v1"

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
    source_kind: Literal["initial", "legacy_save", "settlement"] = "initial"
    source_ref: str | None = None
    imported_at: datetime | None = None
    migration_notes: list[str] = Field(default_factory=list)


class EntitySource(_WorldContract):
    kind: Literal["initial_data", "legacy_save", "adjudication", "system"]
    reference: str | None = None
    summary: str = ""


class PermissionReference(_WorldContract):
    permission_id: PermissionId
    capability: str
    scope_entity_id: EntityId | None = None
    granted_by_entity_id: EntityId | None = None


class RelationshipEdge(_WorldContract):
    relationship_id: RelationId
    relationship_type: str
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


class PlayerWorldStatus(_WorldContract):
    player_character_id: EntityId | None = None
    life_status: Literal["alive", "dead"] = "alive"
    identity_summary: str = ""
    controlled_faction_id: EntityId | None = None
    location_entity_id: EntityId | None = None
    freedom_status: Literal["free", "detained", "exiled", "hidden"] = "free"
    actionable_goal_ids: list[str] = Field(default_factory=list)
    terminal_settlement_id: SettlementId | None = None
    terminal_version_id: VersionId | None = None


class WorldVersionRef(_WorldContract):
    game_id: GameId
    branch_id: BranchId
    version_id: VersionId
    parent_version_id: VersionId | None = None
    settlement_id: SettlementId | None = None
    created_at: datetime
    protected: bool = False
