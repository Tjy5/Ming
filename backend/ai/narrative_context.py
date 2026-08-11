"""Canonical, version-addressed context for player-visible narrative."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai.narrative_registry import (
    NARRATIVE_REGISTRY_VERSION,
    NarrativePathId,
    get_narrative_path,
)
from engine.calendar import ensure_game_time_clock
from engine.world_state import world_state_projection
from models.game import GameEvent, GameState, PolicyProgress, Region
from models.settlement import SettlementFacts
from models.world import (
    Activity,
    ActivityId,
    CalendarProjection,
    CheckpointId,
    Duration,
    EntityId,
    PlayerWorldStatus,
    SettlementId,
    VersionId,
    WorldInstant,
)
from models.world_state import ExecutorFacts, RegionProjection, RollRecord, WorldStateProjection


NARRATIVE_CONTEXT_SCHEMA_VERSION = "narrative-context-v1"


class _NarrativeContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NarrativeMemoryView(_NarrativeContract):
    memory_id: UUID
    source_version_id: VersionId
    source_branch_id: UUID
    mode: str
    phase: str
    chapter: str
    person_entity_id: EntityId | None = None
    topic_id: str
    kind: Literal[
        "raw_recent",
        "commitment",
        "relationship",
        "decision",
        "world_fact",
        "chapter_summary",
        "phase_summary",
    ]
    role: Literal["user", "assistant", "system"]
    content: str
    created_world_hour: int
    created_at: datetime


class NarrativeEntityView(_NarrativeContract):
    entity_id: EntityId
    entity_type: str
    display_name: str
    status: str
    available: bool
    source_kind: str
    source_reference: str | None = None
    permission_capabilities: list[str] = Field(default_factory=list)
    relationship_ids: list[str] = Field(default_factory=list)
    knowledge_boundaries: list[str] = Field(default_factory=list)


class NarrativeTimeView(_NarrativeContract):
    absolute_hour: int
    calendar: CalendarProjection


class NarrativeSourceVersions(_NarrativeContract):
    narrative_registry: str = NARRATIVE_REGISTRY_VERSION
    narrative_context: str = NARRATIVE_CONTEXT_SCHEMA_VERSION
    world_snapshot: int = 1
    settlement_facts: int = 1
    world_state_projection: str = "world-state-projection-v1"
    narrative_memory: str = "narrative-memory-v1"
    calendar: str


class NarrativeActivityView(_NarrativeContract):
    activity_id: ActivityId
    status: str
    intent: str
    started_at: WorldInstant
    ended_at: WorldInstant | None = None
    planned_duration: Duration
    elapsed_hours: int = Field(strict=True, ge=0)
    remaining_hours: int = Field(strict=True, ge=0)
    checkpoint_id: CheckpointId | None = None
    checkpoint_sequence: int | None = Field(default=None, strict=True, ge=1)
    crossed_events: list[str] = Field(default_factory=list)
    interruption_facts: list[str] = Field(default_factory=list)


class NarrativeContext(_NarrativeContract):
    schema_version: Literal["narrative-context-v1"] = NARRATIVE_CONTEXT_SCHEMA_VERSION
    path_id: NarrativePathId
    game_id: UUID | None = None
    branch_id: UUID | None = None
    version_id: VersionId | None = None
    settlement_id: SettlementId | None = None
    mode: str
    phase: str
    chapter: str
    topic_id: str
    person_entity_id: EntityId | None = None
    action_text: str | None = None
    source_versions: NarrativeSourceVersions
    time: NarrativeTimeView
    player: PlayerWorldStatus
    entities: list[NarrativeEntityView]
    activities: list[Activity]
    current_activity: NarrativeActivityView | None = None
    executor: ExecutorFacts | None = None
    rolls: list[RollRecord] = Field(default_factory=list)
    events: list[GameEvent]
    policies: list[PolicyProgress]
    regions: list[RegionProjection]
    legacy_regions: list[Region]
    world_state: WorldStateProjection
    settlement: SettlementFacts | None = None
    memories: list[NarrativeMemoryView] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_identity_alignment(self) -> "NarrativeContext":
        path = get_narrative_path(self.path_id)
        if path.settlement_required and self.settlement is None:
            raise ValueError(f"{self.path_id} requires committed settlement facts")
        if self.settlement is not None:
            facts = self.settlement
            if (
                self.game_id != facts.game_id
                or self.branch_id != facts.branch_id
                or self.version_id != facts.result_version_id
                or self.settlement_id != facts.settlement_id
            ):
                raise ValueError("narrative context identity does not match settlement facts")
        if self.world_state.version_id != self.version_id:
            raise ValueError("world-state projection is not from the context version")
        if any(region.version_id != self.version_id for region in self.regions):
            raise ValueError("region projection is not from the context version")
        if self.settlement is None and (self.executor is not None or self.rolls):
            raise ValueError("executor/roll facts require a committed settlement")
        if self.settlement is not None:
            if self.executor != self.settlement.attribution.executor_facts:
                raise ValueError("narrative executor does not match settlement facts")
            if self.rolls != self.settlement.rolls:
                raise ValueError("narrative rolls do not match settlement facts")
        for memory in self.memories:
            if memory.mode != self.mode or memory.topic_id != self.topic_id:
                raise ValueError("narrative memory is outside the path mode/topic scope")
            if memory.person_entity_id != self.person_entity_id:
                raise ValueError("narrative memory is outside the person/entity scope")
        if path.person_scoped and self.person_entity_id is None:
            raise ValueError(f"{self.path_id} requires a person/entity scope")
        return self


def _time_view(state: GameState) -> NarrativeTimeView:
    game_time = state.time.model_copy(deep=True)
    instant = ensure_game_time_clock(game_time)
    assert game_time.calendar is not None
    return NarrativeTimeView(
        absolute_hour=instant.absolute_hour,
        calendar=game_time.calendar,
    )


def _entity_views(state: GameState) -> list[NarrativeEntityView]:
    return [
        NarrativeEntityView(
            entity_id=entity_id,
            entity_type=entity.entity_type,
            display_name=entity.display_name,
            status=entity.status,
            available=entity.available,
            source_kind=entity.source.kind,
            source_reference=entity.source.reference,
            permission_capabilities=sorted(
                permission.capability for permission in entity.permissions
            ),
            relationship_ids=sorted(
                str(relationship.relationship_id) for relationship in entity.relationships
            ),
            knowledge_boundaries=list(entity.knowledge_boundaries),
        )
        for entity_id, entity in sorted(
            state.entity_registry.items(), key=lambda item: str(item[0]),
        )
    ]


def _current_activity_view(
    state: GameState,
    settlement: SettlementFacts | None,
) -> NarrativeActivityView | None:
    if settlement is None or settlement.activity_id is None:
        return None
    activity = next(
        (item for item in state.activities if item.activity_id == settlement.activity_id),
        None,
    )
    if activity is None:
        raise ValueError("settlement activity is absent from the committed snapshot")
    ended_at = (
        settlement.time_plan.normalized_duration.end
        if settlement.time_plan is not None
        else None
    )
    return NarrativeActivityView(
        activity_id=activity.activity_id,
        status=settlement.activity_status or activity.status,
        intent=activity.intent,
        started_at=activity.started_at,
        ended_at=ended_at,
        planned_duration=activity.planned_duration.model_copy(deep=True),
        elapsed_hours=activity.elapsed_hours,
        remaining_hours=activity.remaining_hours,
        checkpoint_id=settlement.checkpoint_id,
        checkpoint_sequence=settlement.checkpoint_sequence,
        crossed_events=list(settlement.crossed_events),
        interruption_facts=list(activity.interruption_facts),
    )


def _build_narrative_context(
    *,
    path_id: NarrativePathId,
    state: GameState,
    settlement: SettlementFacts | None = None,
    memories: list[NarrativeMemoryView],
    mode: str | None = None,
    topic_id: str = "world",
    person_entity_id: EntityId | None = None,
    action_text: str | None = None,
) -> NarrativeContext:
    """Build one context from a committed snapshot and sibling projections.

    ``memories`` is internal input populated only by the ancestry-aware
    repository query in :func:`build_persisted_narrative_context`.
    """

    metadata = state.world_metadata
    projection = world_state_projection(
        state,
        recent_sources=(
            settlement.world_state_attribution if settlement is not None else ()
        ),
    )
    return NarrativeContext(
        path_id=path_id,
        game_id=metadata.game_id,
        branch_id=metadata.branch_id,
        version_id=metadata.version_id,
        settlement_id=settlement.settlement_id if settlement is not None else None,
        mode=mode or get_narrative_path(path_id).memory_mode,
        phase=state.phase,
        chapter=state.chapter,
        topic_id=topic_id.strip() or "world",
        person_entity_id=person_entity_id,
        action_text=action_text,
        source_versions=NarrativeSourceVersions(
            calendar=metadata.calendar_schema_version,
        ),
        time=_time_view(state),
        player=state.player_world_status.model_copy(deep=True),
        entities=_entity_views(state),
        activities=[activity.model_copy(deep=True) for activity in state.activities],
        current_activity=_current_activity_view(state, settlement),
        executor=(
            settlement.attribution.executor_facts if settlement is not None else None
        ),
        rolls=list(settlement.rolls) if settlement is not None else [],
        events=[event.model_copy(deep=True) for event in state.active_events],
        policies=[policy.model_copy(deep=True) for policy in state.active_policies],
        regions=[region.model_copy(deep=True) for region in projection.regions],
        legacy_regions=[region.model_copy(deep=True) for region in state.regions],
        world_state=projection,
        settlement=settlement,
        memories=list(memories),
    )


def build_narrative_context(
    *,
    path_id: NarrativePathId,
    state: GameState,
    settlement: SettlementFacts | None = None,
    mode: str | None = None,
    topic_id: str = "world",
    person_entity_id: EntityId | None = None,
    action_text: str | None = None,
) -> NarrativeContext:
    """Build a typed context with no process-local or caller-injected memory."""

    return _build_narrative_context(
        path_id=path_id,
        state=state,
        settlement=settlement,
        memories=[],
        mode=mode,
        topic_id=topic_id,
        person_entity_id=person_entity_id,
        action_text=action_text,
    )


def build_persisted_narrative_context(
    *,
    path_id: NarrativePathId,
    state: GameState,
    settlement: SettlementFacts | None = None,
    topic_id: str = "world",
    person_entity_id: EntityId | None = None,
    action_text: str | None = None,
    memory_limit: int = 20,
) -> NarrativeContext:
    """Build context and pull only ancestor-visible retained memory.

    Legacy/uncommitted snapshots have no durable identity and therefore receive
    no persisted memories.  They can still use the typed context for a
    non-settlement query path without falling back to process-global history.
    """

    path = get_narrative_path(path_id)
    metadata = state.world_metadata
    memories: list[NarrativeMemoryView] = []
    if (
        metadata.game_id is not None
        and metadata.branch_id is not None
        and metadata.version_id is not None
    ):
        from db.narrative_memory import list_visible_memories

        records = list_visible_memories(
            game_id=metadata.game_id,
            branch_id=metadata.branch_id,
            version_id=metadata.version_id,
            mode=path.memory_mode,
            topic_id=topic_id.strip() or "world",
            person_entity_id=person_entity_id,
            current_phase=state.phase,
            current_chapter=state.chapter,
            limit=memory_limit,
        )
        memories = [record.to_context_view() for record in records]
    return _build_narrative_context(
        path_id=path_id,
        state=state,
        settlement=settlement,
        memories=memories,
        mode=path.memory_mode,
        topic_id=topic_id,
        person_entity_id=person_entity_id,
        action_text=action_text,
    )
