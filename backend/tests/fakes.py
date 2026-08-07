"""Test-only deterministic AI provider.

Replaces the deleted MockProvider for hermetic tests: every AI call resolves
through the same deterministic rule/template logic the product uses as
failure-time fallbacks (ai/fallbacks). Never registered in production code —
tests register it under AI_PROVIDER=fake via conftest.
"""
from __future__ import annotations

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
from ai.base import AIProvider
from ai.fallbacks import (
    rule_chat_query,
    rule_classify_chat_intent,
    rule_classify_script_choice,
    rule_debate_speeches,
    rule_parse_free_input,
    rule_petitions,
    rule_process_freeform,
    rule_script_trigger_decisions,
    rule_vote_tendency,
    template_action_implications,
    template_assembly_debate,
    template_memorial,
    template_minister_reaction,
    template_narrative,
    template_rejection,
    template_turn_commentary,
)


class FakeProvider(AIProvider):
    async def generate_narrative(
        self,
        delta_attribution: dict,
        game_state: GameState,
        chain_events: list[str],
        decree: StructuredDecree,
        *,
        fix_instruction: str | None = None,
    ) -> str:
        return template_narrative(delta_attribution, game_state, chain_events, decree)

    async def stream_narrative(
        self,
        delta_attribution: dict,
        game_state: GameState,
        chain_events: list[str],
        decree: StructuredDecree,
    ) -> AsyncIterator[str]:
        narrative = template_narrative(delta_attribution, game_state, chain_events, decree)
        if narrative:
            yield narrative

    async def parse_free_input(
        self,
        text: str,
        game_state: GameState,
    ) -> list[StructuredDecree] | dict:
        return rule_parse_free_input(text, game_state)

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        return template_rejection(decree, reason)

    async def generate_debate_narrative(
        self,
        topic: str,
        minister_a: Minister,
        minister_b: Minister,
        game_state: GameState,
    ) -> DebateResult | None:
        return None

    async def generate_memorial(
        self,
        trigger_reason: str,
        author: Minister,
        game_state: GameState,
    ) -> MemorialDraft:
        return template_memorial(trigger_reason, author, game_state)

    async def generate_minister_reaction(
        self,
        minister: Minister,
        decree: StructuredDecree,
        stance: int,
        game_state: GameState,
    ) -> str:
        return template_minister_reaction(minister, decree, stance, game_state)

    async def generate_assembly_debate(
        self,
        topic: str,
        participants: list[Minister],
        game_state: GameState,
    ) -> dict | None:
        return template_assembly_debate(topic, participants, game_state)

    async def generate_petitions(
        self,
        participants: list[Minister],
        game_state: GameState,
    ) -> list[dict]:
        return rule_petitions(participants)

    async def generate_debate_speeches(
        self,
        topic: str,
        participants: list[Minister],
        game_state: GameState,
    ) -> list[dict]:
        return rule_debate_speeches(topic, participants, game_state)

    async def calculate_vote_tendency(
        self,
        minister: Minister,
        decree_type: DecreeType,
        game_state: GameState,
    ) -> str:
        return rule_vote_tendency(minister, decree_type, game_state)

    async def generate_action_implications(
        self,
        summary_data: dict,
        game_state: GameState,
    ) -> list[str]:
        return template_action_implications(summary_data, game_state)

    async def generate_turn_commentary(
        self,
        summary_data: dict,
        game_state: GameState,
    ) -> str:
        return template_turn_commentary(summary_data, game_state)

    async def classify_script_choice(
        self,
        player_text: str,
        script_context: dict | None = None,
        *,
        game_state: GameState | None = None,
    ) -> dict:
        return await rule_classify_script_choice(player_text, script_context)

    async def select_script_trigger_decisions(
        self,
        game_state: GameState,
        candidates: list[dict],
    ) -> dict[str, tuple[bool, str]] | dict:
        return rule_script_trigger_decisions(game_state, candidates)

    async def process_freeform(
        self,
        text: str,
        game_state: GameState,
        *,
        script_context: dict | None = None,
    ) -> FreeformResult | dict:
        return rule_process_freeform(text, game_state)

    async def classify_chat_intent(
        self,
        text: str,
        game_state: GameState,
        conversation_history: list[dict],
    ) -> dict:
        return rule_classify_chat_intent(text, game_state, conversation_history)

    async def chat_query(
        self,
        text: str,
        game_state: GameState,
        conversation_history: list[dict],
    ) -> str:
        return rule_chat_query(text, game_state, conversation_history)

    async def generate_minister_dialogue(
        self,
        minister: Minister,
        message: str,
        game_state: GameState,
        conversation_history: list[dict],
    ) -> dict:
        return rule_minister_dialogue(minister, message, game_state, conversation_history)
