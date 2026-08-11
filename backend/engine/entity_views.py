"""Registry-backed actor views for legacy governance provider interfaces."""

from __future__ import annotations

from dataclasses import dataclass

from models.enums import MinisterStatus
from models.game import GameState, Minister
from models.world import (
    ASSEMBLY_PARTICIPATE_CAPABILITY,
    ENTITY_DIALOGUE_CAPABILITY,
    MEMORIAL_SUBMIT_CAPABILITY,
    OFFICE_APPOINTABLE_CAPABILITY,
    EntityId,
    FactionEntity,
    InstitutionEntity,
    PersonEntity,
    TemporaryAuthorityEntity,
    WorldEntity,
)


ACTOR_ENTITY_TYPES = (
    PersonEntity,
    FactionEntity,
    InstitutionEntity,
    TemporaryAuthorityEntity,
)
ASSEMBLY_ENTITY_TYPES = ACTOR_ENTITY_TYPES


@dataclass(frozen=True)
class ActorCompatibilityView:
    """Stable registry identity plus the temporary Minister shape providers expect."""

    entity_id: EntityId | None
    entity_type: str
    display_name: str
    status: str
    available: bool
    capabilities: tuple[str, ...]
    capability_sources: tuple[str, ...]
    minister: Minister


def _capabilities(entity: WorldEntity) -> tuple[str, ...]:
    return tuple(sorted({permission.capability for permission in entity.permissions}))


def _capability_sources(
    entity: WorldEntity,
    capability: str | None,
) -> tuple[str, ...]:
    return tuple(sorted(
        f"permission:{permission.permission_id}"
        for permission in entity.permissions
        if capability is None or permission.capability == capability
    ))


def _legacy_minister(state: GameState, entity: WorldEntity) -> Minister | None:
    if not isinstance(entity, PersonEntity) or entity.legacy_name is None:
        return None
    return next(
        (minister for minister in state.ministers if minister.name == entity.legacy_name),
        None,
    )


def _faction_name(state: GameState, entity: WorldEntity, legacy: Minister | None) -> str:
    if legacy is not None:
        return legacy.faction
    if isinstance(entity, PersonEntity):
        for faction_id in entity.faction_ids:
            faction = state.entity_registry.get(faction_id)
            if isinstance(faction, FactionEntity):
                return faction.display_name
        return "无派系"
    if isinstance(entity, FactionEntity):
        return entity.display_name
    if isinstance(entity, InstitutionEntity):
        return "机构"
    return "临时权力"


def _positions(entity: WorldEntity, legacy: Minister | None) -> list[str]:
    if isinstance(entity, PersonEntity) and entity.roles:
        return list(entity.roles)
    if legacy is not None:
        return list(legacy.positions)
    if isinstance(entity, InstitutionEntity):
        return [entity.institution_kind]
    if isinstance(entity, FactionEntity):
        return ["势力代表"]
    if isinstance(entity, TemporaryAuthorityEntity):
        return ["临时代理"]
    return []


def _actor_view(
    state: GameState,
    entity: WorldEntity,
    *,
    capability: str | None,
    force_active_legacy: bool = False,
) -> ActorCompatibilityView:
    legacy = _legacy_minister(state, entity)
    faction = _faction_name(state, entity, legacy)
    positions = _positions(entity, legacy)
    if legacy is None:
        minister = Minister(
            name=entity.display_name,
            faction=faction,
            status=MinisterStatus.ACTIVE,
            positions=positions,
            historical_note=entity.source.summary[:200],
        )
    else:
        status = MinisterStatus.ACTIVE if force_active_legacy else legacy.status
        minister = legacy.model_copy(
            deep=True,
            update={
                "name": entity.display_name,
                "faction": faction,
                "positions": positions,
                "status": status,
            },
        )
    return ActorCompatibilityView(
        entity_id=entity.entity_id,
        entity_type=entity.entity_type,
        display_name=entity.display_name,
        status=entity.status,
        available=entity.available,
        capabilities=_capabilities(entity),
        capability_sources=_capability_sources(entity, capability),
        minister=minister,
    )


def _legacy_pre_registry_views(
    state: GameState,
    *,
    capability: str | None,
    include_unavailable: bool,
    legacy_statuses: frozenset[MinisterStatus] | None,
    force_active_legacy: bool,
) -> list[ActorCompatibilityView]:
    """Compatibility only for unit/legacy callers before a world root exists."""

    return [
        ActorCompatibilityView(
            entity_id=None,
            entity_type="person",
            display_name=minister.name,
            status=minister.status.value,
            available=minister.status == MinisterStatus.ACTIVE,
            capabilities=(capability,) if capability is not None else (),
            capability_sources=("legacy-pre-registry-compatibility",),
            minister=minister.model_copy(
                deep=True,
                update={
                    "status": (
                        MinisterStatus.ACTIVE
                        if force_active_legacy
                        else minister.status
                    ),
                },
            ),
        )
        for minister in state.ministers
        if (
            (legacy_statuses is None or minister.status in legacy_statuses)
            and (include_unavailable or minister.status == MinisterStatus.ACTIVE)
        )
    ]


def actor_candidate_views(
    state: GameState,
    *,
    capability: str | None = None,
    entity_types: tuple[type, ...] = ACTOR_ENTITY_TYPES,
    include_unavailable: bool = False,
    legacy_statuses: frozenset[MinisterStatus] | None = None,
    force_active_legacy: bool = False,
) -> list[ActorCompatibilityView]:
    """Project one deterministic actor list from registry identity and permissions.

    ``state.ministers`` is consulted only to fill the temporary provider shape.
    It never adds an actor when a registry exists and cannot override registry
    status, availability, or capability authorization.
    """

    if not state.entity_registry:
        return _legacy_pre_registry_views(
            state,
            capability=capability,
            include_unavailable=include_unavailable,
            legacy_statuses=legacy_statuses,
            force_active_legacy=force_active_legacy,
        )
    views = [
        _actor_view(
            state,
            entity,
            capability=capability,
            force_active_legacy=force_active_legacy,
        )
        for _entity_id, entity in sorted(
            state.entity_registry.items(),
            key=lambda item: str(item[0]),
        )
        if isinstance(entity, entity_types)
        and (
            include_unavailable
            or (entity.status == "active" and entity.available)
        )
        and (capability is None or capability in _capabilities(entity))
    ]
    if legacy_statuses is None:
        return views

    def legacy_status_allowed(actor: ActorCompatibilityView) -> bool:
        entity = state.entity_registry.get(actor.entity_id)
        if not isinstance(entity, PersonEntity):
            return True
        legacy = _legacy_minister(state, entity)
        return legacy is None or legacy.status in legacy_statuses

    return [actor for actor in views if legacy_status_allowed(actor)]


def assembly_actor_views(state: GameState) -> list[ActorCompatibilityView]:
    return actor_candidate_views(
        state,
        capability=ASSEMBLY_PARTICIPATE_CAPABILITY,
        legacy_statuses=frozenset({MinisterStatus.ACTIVE}),
        force_active_legacy=True,
    )


def dialogue_actor_views(state: GameState) -> list[ActorCompatibilityView]:
    return actor_candidate_views(
        state,
        capability=ENTITY_DIALOGUE_CAPABILITY,
        entity_types=(PersonEntity,),
        legacy_statuses=frozenset({MinisterStatus.ACTIVE}),
        force_active_legacy=True,
    )


def memorial_actor_views(state: GameState) -> list[ActorCompatibilityView]:
    return actor_candidate_views(
        state,
        capability=MEMORIAL_SUBMIT_CAPABILITY,
        legacy_statuses=frozenset({MinisterStatus.ACTIVE}),
        force_active_legacy=True,
    )


def appointment_actor_views(state: GameState) -> list[ActorCompatibilityView]:
    return actor_candidate_views(
        state,
        capability=OFFICE_APPOINTABLE_CAPABILITY,
        entity_types=(PersonEntity,),
        legacy_statuses=frozenset({MinisterStatus.ACTIVE, MinisterStatus.IDLE}),
    )


def registry_actor_views(state: GameState) -> list[ActorCompatibilityView]:
    """All actor identities, including inactive/ended ones, for facts guards."""

    return actor_candidate_views(state, include_unavailable=True)


def _resolve_actor(
    views: list[ActorCompatibilityView],
    identity: str,
) -> ActorCompatibilityView | None:
    matches = [
        actor
        for actor in views
        if str(actor.entity_id) == identity or actor.display_name == identity
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def resolve_dialogue_actor(
    state: GameState,
    identity: str,
) -> ActorCompatibilityView | None:
    return _resolve_actor(dialogue_actor_views(state), identity)


def resolve_appointment_actor(
    state: GameState,
    identity: str,
) -> ActorCompatibilityView | None:
    return _resolve_actor(appointment_actor_views(state), identity)


def resolve_registry_actor(
    state: GameState,
    identity: str,
) -> ActorCompatibilityView | None:
    return _resolve_actor(registry_actor_views(state), identity)


def resolve_assembly_actor(
    state: GameState,
    *,
    entity_id: EntityId | None,
    display_name: str,
) -> ActorCompatibilityView | None:
    matches = [
        actor
        for actor in assembly_actor_views(state)
        if (
            actor.entity_id == entity_id
            if entity_id is not None
            else actor.display_name == display_name
        )
    ]
    if len(matches) != 1:
        return None
    return matches[0]
