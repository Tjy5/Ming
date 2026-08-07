from __future__ import annotations

from engine.tables import FACTION_STANCE
from models.game import GameState, Minister, INITIAL_FACTIONS, INITIAL_MINISTERS
from models.enums import DecreeType, MinisterStatus



DEBATE_TOPICS: dict[str, list[dict[str, str]]] = {
    dt.value: [{"topic": topic, "decree_type": dt.value}]
    for dt, topic in {
        DecreeType.TAX_INCREASE: "是否加征赋税以充实国库",
        DecreeType.TAX_DECREASE: "是否减免赋税与民休息",
        DecreeType.RECRUIT_TROOPS: "是否征兵备战",
        DecreeType.DISBAND_TROOPS: "是否裁撤冗兵",
        DecreeType.PERSONNEL: "朝廷人事任免",
        DecreeType.DIPLOMACY: "外交邦交策略",
        DecreeType.DISASTER_RELIEF: "赈灾方略",
        DecreeType.HARSH_PUNISHMENT: "严刑峻法之议",
    }.items()
}

_FACTION_ORDER = {f.name: i for i, f in enumerate(INITIAL_FACTIONS)}


def is_ai_provider(provider) -> bool:
    # Every configured provider is an AI provider; the bundled mock provider
    # was removed. Retained as a predicate for /api/capabilities.
    return True


def _pick_active_minister(state: GameState, faction_name: str) -> Minister | None:
    by_name = {m.name: m for m in state.ministers}
    for tpl in INITIAL_MINISTERS:
        minister = by_name.get(tpl.name)
        if minister and minister.faction == faction_name and minister.status == MinisterStatus.ACTIVE:
            return minister
    return None


def select_debate_ministers(
    state: GameState,
    decree_type: DecreeType,
) -> tuple[Minister, Minister] | None:
    stances = sorted(
        [(name, stance.get(decree_type, 0)) for name, stance in FACTION_STANCE.items()],
        key=lambda x: (-x[1], _FACTION_ORDER.get(x[0], 999)),
    )
    if len(stances) < 2:
        return None

    for pro_name, _ in stances:
        minister_a = _pick_active_minister(state, pro_name)
        if minister_a is None:
            continue
        for opp_name, _ in reversed(stances):
            if opp_name == pro_name:
                continue
            minister_b = _pick_active_minister(state, opp_name)
            if minister_b is not None:
                return minister_a, minister_b
    return None

