from __future__ import annotations

from engine.entity_views import assembly_actor_views
from engine.tables import FACTION_STANCE
from models.game import GameState, Minister, INITIAL_FACTIONS
from models.enums import DecreeType



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


def select_debate_ministers(
    state: GameState,
    decree_type: DecreeType,
) -> tuple[Minister, Minister] | None:
    actors = assembly_actor_views(state)
    ranked = sorted(
        actors,
        key=lambda actor: (
            -FACTION_STANCE.get(actor.minister.faction, {}).get(decree_type, 0),
            _FACTION_ORDER.get(actor.minister.faction, 999),
            str(actor.entity_id or actor.display_name),
        ),
    )
    if len(ranked) < 2:
        return None

    for actor_a in ranked:
        for actor_b in reversed(ranked):
            if actor_b.entity_id == actor_a.entity_id:
                continue
            if actor_b.minister.faction != actor_a.minister.faction:
                return actor_a.minister, actor_b.minister
    return None
