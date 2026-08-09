from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, NewType
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


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
