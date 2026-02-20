import asyncio

import ai.provider as provider_mod
from ai.provider import AIProvider, PARSE_ERROR_TYPE_PARSE, ResilientProvider, parse_error
from models.enums import DecreeType
from models.game import DebateResult, GameState, Minister, StructuredDecree, create_initial_state


class _AlwaysParseErrorProvider(AIProvider):
    async def generate_narrative(
        self,
        delta_attribution: dict,
        game_state: GameState,
        chain_events: list[str],
        decree: StructuredDecree,
    ) -> str:
        return ""

    async def stream_narrative(
        self,
        delta_attribution: dict,
        game_state: GameState,
        chain_events: list[str],
        decree: StructuredDecree,
    ):
        narrative = await self.generate_narrative(
            delta_attribution,
            game_state,
            chain_events,
            decree,
        )
        if narrative:
            yield narrative

    async def parse_free_input(
        self,
        text: str,
        game_state: GameState,
    ) -> list[StructuredDecree] | dict:
        return parse_error("parse failed", PARSE_ERROR_TYPE_PARSE)

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        return ""

    async def generate_debate_narrative(
        self,
        topic: str,
        minister_a: Minister,
        minister_b: Minister,
        game_state: GameState,
    ) -> DebateResult | None:
        return None

    async def generate_portrait(self, minister_name: str, description: str) -> str | None:
        return None

    async def generate_memorial(self, trigger_reason, author, game_state):
        return ""

    async def generate_minister_reaction(self, minister, decree, stance, game_state):
        return ""

    async def generate_assembly_debate(self, topic, participants, game_state):
        return None

    async def generate_turn_commentary(self, summary_data, game_state):
        return ""

    async def generate_minister_dialogue(self, *a, **kw):
        return {}

    async def process_freeform(self, text, game_state):
        return parse_error("not implemented")


def test_parse_fallback_handles_violent_text(monkeypatch):
    monkeypatch.setattr(provider_mod, "_rule_parse_fallback_enabled", True)
    provider = ResilientProvider(_AlwaysParseErrorProvider(), retries=1)
    state = create_initial_state()
    result = asyncio.run(provider.parse_free_input("斩杀所有东陵党", state))

    assert isinstance(result, list)
    assert len(result) >= 1
    assert result[0].type == DecreeType.HARSH_PUNISHMENT


def test_parse_fallback_keeps_error_for_unknown_text(monkeypatch):
    monkeypatch.setattr(provider_mod, "_rule_parse_fallback_enabled", True)
    provider = ResilientProvider(_AlwaysParseErrorProvider(), retries=1)
    state = create_initial_state()
    result = asyncio.run(provider.parse_free_input("asdfghjkl", state))

    assert isinstance(result, dict)
    assert result.get("error_type") == PARSE_ERROR_TYPE_PARSE
