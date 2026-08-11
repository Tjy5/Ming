from __future__ import annotations

from fastapi import HTTPException

from engine.entity_views import (
    ActorCompatibilityView,
    assembly_actor_views,
    resolve_assembly_actor,
)
from models.game import CourtAssembly, ErrorResponse, GameState, Minister
from models.enums import AssemblyPhase
from models.positions import calculate_position_weight


def time_to_months(year: int, month: int) -> int:
    return (year - 1) * 12 + month


MIN_PARTICIPANTS = 10
MAX_PARTICIPANTS = 15


def assembly_position_score(minister: Minister) -> int:
    """Calculate position score for assembly participant selection.

    Uses the cumulative weight from all positions held by the minister.
    """
    return calculate_position_weight(minister.positions)


def normalize_petition_urgency(value: str) -> str:
    raw = (value or "").strip()
    if raw in {"高", "中", "低"}:
        return raw
    return {"high": "高", "medium": "中", "low": "低"}.get(raw.lower(), "中")


def normalize_speech_stance(value: str) -> str:
    raw = (value or "").strip()
    if raw in {"赞成", "反对", "中立"}:
        return raw
    mapping = {"support": "赞成", "oppose": "反对", "neutral": "中立", "abstain": "中立"}
    return mapping.get(raw.lower(), "中立")


def normalize_vote_choice(value: str) -> str:
    raw = (value or "").strip()
    if raw in {"赞成", "反对", "弃权"}:
        return raw
    mapping = {
        "support": "赞成",
        "oppose": "反对",
        "abstain": "弃权",
        "neutral": "弃权",
        "中立": "弃权",
    }
    return mapping.get(raw.lower(), "弃权")


def resolve_assembly_ministers(state: GameState, assembly: CourtAssembly) -> list[Minister]:
    result: list[Minister] = []
    for participant in assembly.participants:
        actor = resolve_assembly_actor(
            state,
            entity_id=participant.entity_id,
            display_name=participant.name,
        )
        if actor is not None:
            result.append(actor.minister)
    return result


def require_assembly(
    state: GameState,
    allowed: set[AssemblyPhase] | None = None,
) -> CourtAssembly:
    assembly = state.last_assembly
    if assembly is None:
        raise HTTPException(
            400,
            detail=ErrorResponse(
                error_code="no_assembly",
                message="当前无进行中的朝会",
            ).model_dump(),
        )
    if allowed and assembly.phase not in allowed:
        raise HTTPException(
            400,
            detail=ErrorResponse(
                error_code="invalid_assembly_phase",
                message=f"当前阶段为 {assembly.phase.value}，无法执行该操作",
            ).model_dump(),
        )
    return assembly


def select_assembly_actor_views(state: GameState) -> list[ActorCompatibilityView]:
    active = assembly_actor_views(state)
    if not active:
        return []
    order_map = {
        actor.entity_id or actor.display_name: index
        for index, actor in enumerate(active)
    }

    def score(actor: ActorCompatibilityView) -> tuple[int, int, int, int]:
        m = actor.minister
        ability_total = m.abilities.civil + m.abilities.military + m.abilities.diplomacy
        return (
            assembly_position_score(m),
            m.loyalty,
            ability_total,
            -order_map.get(actor.entity_id or actor.display_name, 9999),
        )

    by_faction: dict[str, list[ActorCompatibilityView]] = {}
    for actor in active:
        by_faction.setdefault(actor.minister.faction, []).append(actor)

    participants: list[ActorCompatibilityView] = []
    selected_ids: set[object] = set()
    for faction_actors in by_faction.values():
        rep = max(faction_actors, key=score)
        participants.append(rep)
        selected_ids.add(rep.entity_id or rep.display_name)

    remaining = sorted(
        [
            actor for actor in active
            if (actor.entity_id or actor.display_name) not in selected_ids
        ],
        key=score,
        reverse=True,
    )
    target_count = min(MAX_PARTICIPANTS, max(MIN_PARTICIPANTS, len(participants)))
    for minister in remaining:
        if len(participants) >= target_count:
            break
        participants.append(minister)
    return sorted(participants, key=score, reverse=True)[:MAX_PARTICIPANTS]


def select_assembly_participants(state: GameState) -> list[Minister]:
    """Compatibility wrapper for provider and older unit-test callers."""

    return [actor.minister for actor in select_assembly_actor_views(state)]
