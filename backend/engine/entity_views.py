"""Registry-backed actor views for legacy governance provider interfaces."""

from __future__ import annotations

from dataclasses import dataclass

from models.enums import MinisterStatus
from models.game import GameState, Minister
from models.world import (
    ASSEMBLY_PARTICIPATE_CAPABILITY,
    ENTITY_DIALOGUE_CAPABILITY,
    EntityId,
    FactionEntity,
    InstitutionEntity,
    PersonEntity,
    TemporaryAuthorityEntity,
    WorldEntity,
)


ASSEMBLY_ENTITY_TYPES = (
    PersonEntity,
    FactionEntity,
    InstitutionEntity,
    TemporaryAuthorityEntity,
)


@dataclass(frozen=True)
class ActorCompatibilityView:
    """Stable registry identity plus the temporary Minister shape providers expect."""

    entity_id: EntityId | None
    entity_type: str
    display_name: str
    capabilities: tuple[str, ...]
    capability_sources: tuple[str, ...]
    minister: Minister


def _capabilities(entity: WorldEntity) -> tuple[str, ...]:
    return tuple(sorted({permission.capability for permission in entity.permissions}))


def _capability_sources(entity: WorldEntity, capability: str) -> tuple[str, ...]:
    return tuple(sorted(
        f"permission:{permission.permission_id}"
        for permission in entity.permissions
        if permission.capability == capability
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
    capability: str,
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
        minister = legacy.model_copy(
            deep=True,
            update={
                "name": entity.display_name,
                "faction": faction,
                "positions": positions,
                "status": MinisterStatus.ACTIVE,
            },
        )
    return ActorCompatibilityView(
        entity_id=entity.entity_id,
        entity_type=entity.entity_type,
        display_name=entity.display_name,
        capabilities=_capabilities(entity),
        capability_sources=_capability_sources(entity, capability),
        minister=minister,
    )


def _legacy_pre_registry_views(
    state: GameState,
    *,
    capability: str,
) -> list[ActorCompatibilityView]:
    """Compatibility only for unit/legacy callers before a world root exists."""

    return [
        ActorCompatibilityView(
            entity_id=None,
            entity_type="person",
            display_name=minister.name,
            capabilities=(capability,),
            capability_sources=("legacy-pre-registry-compatibility",),
            minister=minister.model_copy(deep=True),
        )
        for minister in state.ministers
        if minister.status == MinisterStatus.ACTIVE
    ]


def assembly_actor_views(state: GameState) -> list[ActorCompatibilityView]:
    if not state.entity_registry:
        return _legacy_pre_registry_views(
            state,
            capability=ASSEMBLY_PARTICIPATE_CAPABILITY,
        )
    return [
        _actor_view(state, entity, capability=ASSEMBLY_PARTICIPATE_CAPABILITY)
        for _entity_id, entity in sorted(
            state.entity_registry.items(),
            key=lambda item: str(item[0]),
        )
        if isinstance(entity, ASSEMBLY_ENTITY_TYPES)
        and entity.status == "active"
        and entity.available
        and ASSEMBLY_PARTICIPATE_CAPABILITY in _capabilities(entity)
    ]


def dialogue_actor_views(state: GameState) -> list[ActorCompatibilityView]:
    if not state.entity_registry:
        return _legacy_pre_registry_views(
            state,
            capability=ENTITY_DIALOGUE_CAPABILITY,
        )
    return [
        _actor_view(state, entity, capability=ENTITY_DIALOGUE_CAPABILITY)
        for _entity_id, entity in sorted(
            state.entity_registry.items(),
            key=lambda item: str(item[0]),
        )
        if isinstance(entity, PersonEntity)
        and entity.status == "active"
        and entity.available
        and ENTITY_DIALOGUE_CAPABILITY in _capabilities(entity)
    ]


def resolve_dialogue_actor(
    state: GameState,
    identity: str,
) -> ActorCompatibilityView | None:
    matches = [
        actor
        for actor in dialogue_actor_views(state)
        if str(actor.entity_id) == identity or actor.display_name == identity
    ]
    if len(matches) != 1:
        return None
    return matches[0]


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
