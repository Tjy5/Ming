from __future__ import annotations

import abc
import os
from collections.abc import AsyncIterator

from models.game import (
    DebateResult,
    FreeformResult,
    GameState,
    MemorialDraft,
    Minister,
    StructuredDecree,
)
from models.enums import DecreeType

PARSE_ERROR_TYPE_PARSE = "parse_error"
PARSE_ERROR_TYPE_UNAVAILABLE = "service_unavailable"


def parse_error(message: str, error_type: str = PARSE_ERROR_TYPE_PARSE) -> dict:
    return {"error": message, "error_type": error_type}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


_rule_parse_fallback_enabled = _env_bool("AI_RULE_PARSE_FALLBACK", False)


def get_rule_parse_fallback() -> bool:
    try:
        import ai.provider as provider_mod

        marker = getattr(provider_mod, "_rule_parse_fallback_enabled", None)
        if isinstance(marker, bool):
            return marker
    except Exception:
        pass
    return _rule_parse_fallback_enabled


def set_rule_parse_fallback(enabled: bool) -> None:
    global _rule_parse_fallback_enabled
    _rule_parse_fallback_enabled = enabled
    try:
        import ai.provider as provider_mod

        provider_mod._rule_parse_fallback_enabled = enabled
    except Exception:
        pass


def mock_fallback_enabled() -> bool:
    """Whether runtime is allowed to downgrade failed AI calls to MockProvider."""
    raw_override = os.getenv("AI_ENABLE_MOCK_FALLBACK")
    if raw_override is not None:
        return _env_bool("AI_ENABLE_MOCK_FALLBACK", False)
    provider = (os.getenv("AI_PROVIDER") or "").strip().lower()
    return provider == "mock"




class AIProvider(abc.ABC):
    @abc.abstractmethod
    async def generate_narrative(
        self,
        delta_attribution: dict,
        game_state: GameState,
        chain_events: list[str],
        decree: StructuredDecree,
    ) -> str: ...

    @abc.abstractmethod
    async def stream_narrative(
        self,
        delta_attribution: dict,
        game_state: GameState,
        chain_events: list[str],
        decree: StructuredDecree,
    ) -> AsyncIterator[str]: ...

    @abc.abstractmethod
    async def parse_free_input(
        self,
        text: str,
        game_state: GameState,
    ) -> list[StructuredDecree] | dict: ...

    @abc.abstractmethod
    async def rejection_narrative(
        self,
        decree: StructuredDecree,
        reason: str,
    ) -> str: ...

    @abc.abstractmethod
    async def generate_debate_narrative(
        self,
        topic: str,
        minister_a: Minister,
        minister_b: Minister,
        game_state: GameState,
    ) -> DebateResult | None: ...

    @abc.abstractmethod
    async def generate_memorial(
        self,
        trigger_reason: str,
        author: Minister,
        game_state: GameState,
    ) -> MemorialDraft: ...

    @abc.abstractmethod
    async def generate_minister_reaction(
        self,
        minister: Minister,
        decree: StructuredDecree,
        stance: int,
        game_state: GameState,
    ) -> str: ...

    @abc.abstractmethod
    async def generate_assembly_debate(
        self,
        topic: str,
        participants: list[Minister],
        game_state: GameState,
    ) -> dict | None: ...

    async def generate_petitions(
        self,
        participants: list[Minister],
        game_state: GameState,
    ) -> list[dict]:
        petitions: list[dict] = []
        for minister in participants:
            urgency = "中"
            if minister.abilities.military >= 80:
                urgency = "高"
            elif minister.abilities.civil < 40 and minister.loyalty < 40:
                urgency = "低"
            petitions.append(
                {
                    "minister_name": minister.name,
                    "content": f"臣{minister.name}谨奏：当下{minister.faction}所忧之政务，宜速议定施行。",
                    "urgency": urgency,
                }
            )
        return petitions

    async def generate_debate_speeches(
        self,
        topic: str,
        participants: list[Minister],
        game_state: GameState,
    ) -> list[dict]:
        decree_type = infer_decree_type_from_topic(topic) or DecreeType.PERSONNEL
        speeches: list[dict] = []
        for minister in participants:
            tendency = await self.calculate_vote_tendency(minister, decree_type, game_state)
            stance = "中立"
            if tendency == "赞成":
                stance = "赞成"
            elif tendency == "反对":
                stance = "反对"
            speeches.append(
                {
                    "minister_name": minister.name,
                    "faction": minister.faction,
                    "content": (
                        f"臣{minister.name}以为'{topic}'当"
                        f"{('力行' if stance == '赞成' else '慎行' if stance == '反对' else '缓议')}，请陛下裁断。"
                    ),
                    "stance": stance,
                }
            )
        return speeches

    async def calculate_vote_tendency(
        self,
        minister: Minister,
        decree_type: DecreeType,
        game_state: GameState,
    ) -> str:
        try:
            from engine.tables import FACTION_STANCE

            faction_stance = int(FACTION_STANCE.get(minister.faction, {}).get(decree_type, 0))
        except Exception:
            faction_stance = 0
        score = faction_stance + (minister.loyalty - 50) / 3
        if score >= 12:
            return "赞成"
        if score <= -12:
            return "反对"
        return "弃权"

    async def generate_action_implications(
        self,
        summary_data: dict,
        game_state: GameState,
    ) -> list[str]:
        return []

    @abc.abstractmethod
    async def generate_turn_commentary(
        self,
        summary_data: dict,
        game_state: GameState,
    ) -> str: ...

    @abc.abstractmethod
    async def classify_script_choice(
        self,
        player_text: str,
        script_context: dict | None = None,
        *,
        game_state: GameState | None = None,
    ) -> dict: ...

    @abc.abstractmethod
    async def select_script_trigger_decisions(
        self,
        game_state: GameState,
        candidates: list[dict],
    ) -> dict[str, tuple[bool, str]] | dict: ...

    @abc.abstractmethod
    async def process_freeform(
        self,
        text: str,
        game_state: GameState,
        *,
        script_context: dict | None = None,
    ) -> FreeformResult | dict: ...

    @abc.abstractmethod
    async def generate_minister_dialogue(
        self,
        minister: Minister,
        message: str,
        game_state: GameState,
        conversation_history: list[dict],
    ) -> dict: ...


_TOPIC_DECREE_HINTS: list[tuple[DecreeType, tuple[str, ...]]] = [
    (DecreeType.TAX_INCREASE, ("加税", "赋税", "税负", "税赋")),
    (DecreeType.TAX_DECREASE, ("减税", "免税", "税负减免")),
    (DecreeType.RECRUIT_TROOPS, ("募兵", "征兵", "增兵", "练兵")),
    (DecreeType.DISBAND_TROOPS, ("裁兵", "撤军", "裁撤")),
    (DecreeType.PERSONNEL, ("任命", "罢免", "任免", "廷推", "官职")),
    (DecreeType.DIPLOMACY, ("外交", "议和", "出使", "盟约")),
    (DecreeType.DISASTER_RELIEF, ("赈灾", "救灾", "灾荒", "赈济")),
    (DecreeType.HARSH_PUNISHMENT, ("严刑", "峻法", "重典", "惩治")),
]


def infer_decree_type_from_topic(topic: str) -> DecreeType | None:
    text = (topic or "").strip()
    if not text:
        return None
    for decree_type, keywords in _TOPIC_DECREE_HINTS:
        if any(keyword in text for keyword in keywords):
            return decree_type
    return None
