"""Deterministic executor projections used by world-state application."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from models.enums import MinisterStatus
from models.game import GameState, Minister
from models.world import (
    EntityId,
    FactionEntity,
    InstitutionEntity,
    PersonEntity,
    TemporaryAuthorityEntity,
)
from models.world_state import ExecutorCandidateProjection, ExecutorFactor, ExecutorFacts
from engine.entity_views import actor_candidate_views


MIN_EXECUTOR_EFFICIENCY = Decimal("0.05")
EXECUTOR_ENTITY_TYPES = (
    PersonEntity,
    FactionEntity,
    InstitutionEntity,
    TemporaryAuthorityEntity,
)
_ABILITY_BY_ACTION = {
    "warfare": "military",
    "infiltration": "knowledge",
    "escape": "military",
    "diplomacy": "diplomacy",
    "governance": "administration",
}


def _bounded_ratio(value: int | float) -> Decimal:
    bounded = max(0, min(100, int(value)))
    return Decimal(bounded) / Decimal(100)


def _legacy_minister(state: GameState, entity: PersonEntity) -> Minister | None:
    name = entity.legacy_name or entity.display_name
    return next((minister for minister in state.ministers if minister.name == name), None)


def legacy_minister_efficiency(
    minister: Minister,
    action_kind: str | None,
) -> tuple[list[ExecutorFactor], Decimal]:
    ability_name = _ABILITY_BY_ACTION.get(action_kind or "", "civil")
    ability = _bounded_ratio(getattr(minister.abilities, ability_name, minister.abilities.civil))
    loyalty = _bounded_ratio(minister.loyalty)
    integrity = Decimal("1") - _bounded_ratio(minister.corruption)
    authority = Decimal("1") if minister.positions else Decimal("0.6")
    availability = Decimal("1") if minister.status == MinisterStatus.ACTIVE else Decimal("0")
    factors = [
        ExecutorFactor(name="capability", value=ability, source=f"minister.abilities.{ability_name}"),
        ExecutorFactor(name="loyalty", value=loyalty, source="minister.loyalty"),
        ExecutorFactor(name="integrity", value=integrity, source="minister.corruption"),
        ExecutorFactor(name="authority", value=authority, source="minister.positions"),
        ExecutorFactor(name="availability", value=availability, source="minister.status"),
    ]
    if availability == 0:
        return factors, Decimal("0")
    efficiency = (
        ability * Decimal("0.35")
        + loyalty * Decimal("0.25")
        + integrity * Decimal("0.25")
        + authority * Decimal("0.15")
    ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return factors, max(MIN_EXECUTOR_EFFICIENCY, min(Decimal("1"), efficiency))


def _person_factors(
    state: GameState,
    entity: PersonEntity,
    action_kind: str | None,
) -> tuple[list[ExecutorFactor], Decimal]:
    minister = _legacy_minister(state, entity)
    if minister is None:
        authority = Decimal("1") if entity.permissions else Decimal("0.5")
        factors = [ExecutorFactor(name="authority", value=authority, source="entity.permissions")]
        return factors, max(MIN_EXECUTOR_EFFICIENCY, authority)
    return legacy_minister_efficiency(minister, action_kind)


def build_executor_facts(
    state: GameState,
    *,
    requested_executor_id: EntityId | None,
    actual_executor_id: EntityId | None,
    execution_status: str,
    action_kind: str | None = None,
) -> ExecutorFacts:
    selection_source = (
        "player" if requested_executor_id is not None else "ai" if actual_executor_id is not None else "none"
    )
    if actual_executor_id is None:
        return ExecutorFacts(
            requested_executor_id=requested_executor_id,
            actual_executor_id=None,
            selection_source=selection_source,
            execution_status=execution_status,
            version_id=state.world_metadata.version_id,
            efficiency=Decimal("1"),
        )

    entity = state.entity_registry.get(actual_executor_id)
    if entity is None:
        raise ValueError("actual executor does not exist in the current entity registry")
    if not isinstance(entity, EXECUTOR_ENTITY_TYPES):
        raise ValueError("actual executor must be a person, faction, institution, or temporary authority")

    if isinstance(entity, PersonEntity):
        factors, efficiency = _person_factors(state, entity, action_kind)
    elif isinstance(entity, FactionEntity):
        influence = _bounded_ratio(entity.influence or 0)
        availability = Decimal("1") if entity.available and entity.status == "active" else Decimal("0")
        factors = [
            ExecutorFactor(name="influence", value=influence, source="entity.influence"),
            ExecutorFactor(name="availability", value=availability, source="entity.status"),
        ]
        efficiency = max(MIN_EXECUTOR_EFFICIENCY, influence) if availability else Decimal("0")
    else:
        authority = Decimal("1") if entity.permissions else Decimal("0.6")
        availability = Decimal("1") if entity.available and entity.status == "active" else Decimal("0")
        factors = [
            ExecutorFactor(name="authority", value=authority, source="entity.permissions"),
            ExecutorFactor(name="availability", value=availability, source="entity.status"),
        ]
        efficiency = authority if availability else Decimal("0")

    return ExecutorFacts(
        requested_executor_id=requested_executor_id,
        actual_executor_id=actual_executor_id,
        selection_source=selection_source,
        execution_status=execution_status,
        entity_type=entity.entity_type,
        display_name=entity.display_name,
        version_id=state.world_metadata.version_id,
        factors=factors,
        efficiency=efficiency,
    )


def executor_candidates(state: GameState, action_kind: str | None = None) -> list[ExecutorCandidateProjection]:
    candidates: list[ExecutorCandidateProjection] = []
    if not state.entity_registry:
        return candidates
    for actor in actor_candidate_views(state, include_unavailable=True):
        entity_id = actor.entity_id
        if entity_id is None:
            continue
        entity = state.entity_registry[entity_id]
        facts = build_executor_facts(
            state,
            requested_executor_id=None,
            actual_executor_id=entity_id,
            execution_status="candidate",
            action_kind=action_kind,
        )
        risks = [factor.name for factor in facts.factors if factor.value < Decimal("0.35")]
        candidates.append(
            ExecutorCandidateProjection(
                version_id=state.world_metadata.version_id,
                executor=facts,
                available=actor.available and actor.status == "active",
                authority=list(actor.capabilities),
                risks=risks,
            ),
        )
    return candidates
