from __future__ import annotations

from fastapi import HTTPException

from models.game import CourtAssembly, ErrorResponse, GameState, Minister
from models.enums import AssemblyPhase, MinisterStatus


def time_to_months(year: int, month: int) -> int:
    return (year - 1) * 12 + month


MIN_PARTICIPANTS = 10
MAX_PARTICIPANTS = 15
_POSITION_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("首辅", 120),
    ("次辅", 115),
    ("大学士", 110),
    ("尚书", 100),
    ("侍郎", 90),
    ("都御史", 85),
    ("巡抚", 80),
    ("总督", 80),
    ("总兵", 78),
)


def assembly_position_score(position: str) -> int:
    pos = (position or "").strip()
    score = 0
    for key, weight in _POSITION_WEIGHTS:
        if key in pos:
            score = max(score, weight)
    return score


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
    active_by_name = {m.name: m for m in state.ministers if m.status == MinisterStatus.ACTIVE}
    result: list[Minister] = []
    for p in assembly.participants:
        m = active_by_name.get(p.name)
        if m is not None:
            result.append(m)
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


def select_assembly_participants(state: GameState) -> list[Minister]:
    active = [m for m in state.ministers if m.status == MinisterStatus.ACTIVE]
    if not active:
        return []
    order_map = {m.name: idx for idx, m in enumerate(state.ministers)}

    def score(m: Minister) -> tuple[int, int, int, int]:
        ability_total = m.abilities.civil + m.abilities.military + m.abilities.diplomacy
        return (
            assembly_position_score(m.position),
            m.loyalty,
            ability_total,
            -order_map.get(m.name, 9999),
        )

    by_faction: dict[str, list[Minister]] = {}
    for minister in active:
        by_faction.setdefault(minister.faction, []).append(minister)

    participants: list[Minister] = []
    selected_names: set[str] = set()
    for faction_ministers in by_faction.values():
        rep = max(faction_ministers, key=score)
        participants.append(rep)
        selected_names.add(rep.name)

    remaining = sorted(
        [m for m in active if m.name not in selected_names],
        key=score,
        reverse=True,
    )
    target_count = min(MAX_PARTICIPANTS, max(MIN_PARTICIPANTS, len(participants)))
    for minister in remaining:
        if len(participants) >= target_count:
            break
        participants.append(minister)
    return sorted(participants, key=score, reverse=True)[:MAX_PARTICIPANTS]

