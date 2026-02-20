from __future__ import annotations

import asyncio
import logging
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

from .base import (
    AIProvider,
    PARSE_ERROR_TYPE_UNAVAILABLE,
    _env_float,
    _env_int,
    _is_non_retryable_portrait_error,
    get_rule_parse_fallback,
    parse_error,
)
from .mock_provider import MockProvider
from .parsers import _validate_decrees


async def _local_rule_parse(
    text: str,
    game_state: GameState,
) -> list[StructuredDecree] | None:
    fallback = await MockProvider().parse_free_input(text, game_state)
    if isinstance(fallback, dict):
        return None
    validated = _validate_decrees(fallback)
    if isinstance(validated, dict):
        return None
    return validated


class ResilientProvider(AIProvider):
    """Wraps any AIProvider with timeout, retry, and output validation."""

    def __init__(
        self,
        inner: AIProvider,
        timeout: float | None = None,
        retries: int | None = None,
        parse_timeout: float | None = None,
        parse_retries: int | None = None,
        freeform_timeout: float | None = None,
        freeform_retries: int | None = None,
        turn_commentary_timeout: float | None = None,
        turn_commentary_retries: int | None = None,
    ):
        self._inner = inner
        env_timeout = _env_float("AI_TIMEOUT", 30.0)
        env_retries = _env_int("AI_RETRIES", 3)
        base_timeout = timeout if timeout is not None else env_timeout
        base_retries = retries if retries is not None else env_retries
        self._timeout = max(0.1, base_timeout)
        self._retries = max(1, base_retries)
        env_parse_timeout = _env_float("AI_PARSE_TIMEOUT", 60.0)
        env_parse_retries = _env_int("AI_PARSE_RETRIES", 1)
        env_freeform_timeout = _env_float("AI_FREEFORM_TIMEOUT", 90.0)
        env_freeform_retries = _env_int("AI_FREEFORM_RETRIES", 1)
        env_turn_commentary_timeout = _env_float("AI_TURN_COMMENTARY_TIMEOUT", 90.0)
        env_turn_commentary_retries = _env_int("AI_TURN_COMMENTARY_RETRIES", 1)
        self._parse_timeout = max(0.1, parse_timeout if parse_timeout is not None else env_parse_timeout)
        self._parse_retries = max(1, parse_retries if parse_retries is not None else env_parse_retries)
        self._freeform_timeout = max(
            0.1,
            freeform_timeout if freeform_timeout is not None else env_freeform_timeout,
        )
        self._freeform_retries = max(
            1,
            freeform_retries if freeform_retries is not None else env_freeform_retries,
        )
        self._turn_commentary_timeout = max(
            0.1,
            turn_commentary_timeout if turn_commentary_timeout is not None else env_turn_commentary_timeout,
        )
        self._turn_commentary_retries = max(
            1,
            turn_commentary_retries if turn_commentary_retries is not None else env_turn_commentary_retries,
        )

    @staticmethod
    def _log_retry_failure(operation: str, attempt: int, retries: int, exc: Exception) -> None:
        msg = str(exc).strip()
        err_type = type(exc).__name__
        if msg:
            logging.error("%s attempt %d/%d failed (%s): %s", operation, attempt, retries, err_type, msg)
        else:
            logging.error("%s attempt %d/%d failed (%s)", operation, attempt, retries, err_type)

    async def generate_narrative(
        self,
        delta_attribution: dict,
        game_state: GameState,
        chain_events: list[str],
        decree: StructuredDecree,
    ) -> str:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.generate_narrative(delta_attribution, game_state, chain_events, decree),
                    timeout=self._timeout,
                )
            except Exception as e:
                self._log_retry_failure("generate_narrative", attempt + 1, self._retries, e)
                if attempt == self._retries - 1:
                    return "（AI服务响应异常，但政令已执行）"
        return "（AI服务响应异常，但政令已执行）"

    async def stream_narrative(
        self,
        delta_attribution: dict,
        game_state: GameState,
        chain_events: list[str],
        decree: StructuredDecree,
    ) -> AsyncIterator[str]:
        emitted_any = False
        for attempt in range(self._retries):
            stream_iter = None
            try:
                stream_iter = self._inner.stream_narrative(
                    delta_attribution,
                    game_state,
                    chain_events,
                    decree,
                )
                while True:
                    chunk = await asyncio.wait_for(anext(stream_iter), timeout=self._timeout)
                    if not chunk:
                        continue
                    emitted_any = True
                    yield chunk
            except StopAsyncIteration:
                return
            except Exception as e:
                self._log_retry_failure("stream_narrative", attempt + 1, self._retries, e)
                if emitted_any:
                    return
                if attempt == self._retries - 1:
                    yield "（AI服务响应异常，但政令已执行）"
                    return
            finally:
                close = getattr(stream_iter, "aclose", None)
                if callable(close):
                    try:
                        await close()
                    except Exception:
                        pass

    async def parse_free_input(
        self,
        text: str,
        game_state: GameState,
    ) -> list[StructuredDecree] | dict:
        for attempt in range(self._parse_retries):
            try:
                result = await asyncio.wait_for(
                    self._inner.parse_free_input(text, game_state),
                    timeout=self._parse_timeout,
                )
                if isinstance(result, dict):
                    if get_rule_parse_fallback():
                        fallback = await _local_rule_parse(text, game_state)
                        if fallback is not None:
                            return fallback
                    return result
                return _validate_decrees(result)
            except Exception as e:
                self._log_retry_failure("parse_free_input", attempt + 1, self._parse_retries, e)
                if attempt == self._parse_retries - 1:
                    if get_rule_parse_fallback():
                        fallback = await _local_rule_parse(text, game_state)
                        if fallback is not None:
                            return fallback
                    return parse_error(
                        "AI模型服务不可用：可能原因包括API密钥失效、模型配额耗尽、网络连接异常或服务商限流。请检查后端配置或开启本地规则兜底。",
                        PARSE_ERROR_TYPE_UNAVAILABLE,
                    )
        if get_rule_parse_fallback():
            fallback = await _local_rule_parse(text, game_state)
            if fallback is not None:
                return fallback
        return parse_error(
            "AI模型服务不可用：可能原因包括API密钥失效、模型配额耗尽、网络连接异常或服务商限流。请检查后端配置或开启本地规则兜底。",
            PARSE_ERROR_TYPE_UNAVAILABLE,
        )

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.rejection_narrative(decree, reason),
                    timeout=self._timeout,
                )
            except Exception as e:
                self._log_retry_failure("rejection_narrative", attempt + 1, self._retries, e)
                if attempt == self._retries - 1:
                    return f"此令无法执行：{reason}"
        return f"此令无法执行：{reason}"

    async def generate_debate_narrative(
        self,
        topic: str,
        minister_a: Minister,
        minister_b: Minister,
        game_state: GameState,
    ) -> DebateResult | None:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.generate_debate_narrative(topic, minister_a, minister_b, game_state),
                    timeout=self._timeout,
                )
            except Exception as e:
                self._log_retry_failure("generate_debate_narrative", attempt + 1, self._retries, e)
                if attempt == self._retries - 1:
                    return None
        return None

    async def generate_portrait(self, minister_name: str, description: str) -> str | None:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.generate_portrait(minister_name, description),
                    timeout=self._timeout,
                )
            except Exception as e:
                self._log_retry_failure("generate_portrait", attempt + 1, self._retries, e)
                if _is_non_retryable_portrait_error(e):
                    return None
                if attempt == self._retries - 1:
                    return None
        return None

    async def generate_memorial(
        self,
        trigger_reason: str,
        author: Minister,
        game_state: GameState,
    ) -> MemorialDraft:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.generate_memorial(trigger_reason, author, game_state),
                    timeout=self._timeout,
                )
            except Exception as e:
                self._log_retry_failure("generate_memorial", attempt + 1, self._retries, e)
                if attempt == self._retries - 1:
                    return await MockProvider().generate_memorial(trigger_reason, author, game_state)
        return await MockProvider().generate_memorial(trigger_reason, author, game_state)

    async def generate_minister_reaction(
        self,
        minister: Minister,
        decree: StructuredDecree,
        stance: int,
        game_state: GameState,
    ) -> str:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.generate_minister_reaction(minister, decree, stance, game_state),
                    timeout=self._timeout,
                )
            except Exception as e:
                self._log_retry_failure("generate_minister_reaction", attempt + 1, self._retries, e)
                if attempt == self._retries - 1:
                    return await MockProvider().generate_minister_reaction(minister, decree, stance, game_state)
        return await MockProvider().generate_minister_reaction(minister, decree, stance, game_state)

    async def generate_assembly_debate(
        self,
        topic: str,
        participants: list[Minister],
        game_state: GameState,
    ) -> dict | None:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.generate_assembly_debate(topic, participants, game_state),
                    timeout=self._timeout,
                )
            except Exception as e:
                self._log_retry_failure("generate_assembly_debate", attempt + 1, self._retries, e)
                if attempt == self._retries - 1:
                    return None
        return None

    async def generate_petitions(
        self,
        participants: list[Minister],
        game_state: GameState,
    ) -> list[dict]:
        for attempt in range(self._retries):
            try:
                petitions = await asyncio.wait_for(
                    self._inner.generate_petitions(participants, game_state),
                    timeout=self._timeout,
                )
                if petitions:
                    return petitions
            except Exception as e:
                self._log_retry_failure("generate_petitions", attempt + 1, self._retries, e)
                if attempt == self._retries - 1:
                    return await MockProvider().generate_petitions(participants, game_state)
        return await MockProvider().generate_petitions(participants, game_state)

    async def generate_debate_speeches(
        self,
        topic: str,
        participants: list[Minister],
        game_state: GameState,
    ) -> list[dict]:
        for attempt in range(self._retries):
            try:
                speeches = await asyncio.wait_for(
                    self._inner.generate_debate_speeches(topic, participants, game_state),
                    timeout=self._timeout,
                )
                if speeches:
                    return speeches
            except Exception as e:
                self._log_retry_failure("generate_debate_speeches", attempt + 1, self._retries, e)
                if attempt == self._retries - 1:
                    return await MockProvider().generate_debate_speeches(topic, participants, game_state)
        return await MockProvider().generate_debate_speeches(topic, participants, game_state)

    async def calculate_vote_tendency(
        self,
        minister: Minister,
        decree_type: DecreeType,
        game_state: GameState,
    ) -> str:
        for attempt in range(self._retries):
            try:
                vote = await asyncio.wait_for(
                    self._inner.calculate_vote_tendency(minister, decree_type, game_state),
                    timeout=self._timeout,
                )
                if vote in {"赞成", "反对", "弃权"}:
                    return vote
                return "弃权"
            except Exception as e:
                self._log_retry_failure("calculate_vote_tendency", attempt + 1, self._retries, e)
                if attempt == self._retries - 1:
                    return await MockProvider().calculate_vote_tendency(minister, decree_type, game_state)
        return await MockProvider().calculate_vote_tendency(minister, decree_type, game_state)

    async def generate_action_implications(
        self,
        summary_data: dict,
        game_state: GameState,
    ) -> list[str]:
        for attempt in range(self._retries):
            try:
                result = await asyncio.wait_for(
                    self._inner.generate_action_implications(summary_data, game_state),
                    timeout=self._timeout,
                )
                return [str(x) for x in (result or [])][:3]
            except Exception as e:
                self._log_retry_failure("generate_action_implications", attempt + 1, self._retries, e)
        return await MockProvider().generate_action_implications(summary_data, game_state)

    async def generate_turn_commentary(
        self,
        summary_data: dict,
        game_state: GameState,
    ) -> str:
        for attempt in range(self._turn_commentary_retries):
            try:
                return await asyncio.wait_for(
                    self._inner.generate_turn_commentary(summary_data, game_state),
                    timeout=self._turn_commentary_timeout,
                )
            except Exception as e:
                self._log_retry_failure(
                    "generate_turn_commentary",
                    attempt + 1,
                    self._turn_commentary_retries,
                    e,
                )
                if attempt == self._turn_commentary_retries - 1:
                    return await MockProvider().generate_turn_commentary(summary_data, game_state)
        return await MockProvider().generate_turn_commentary(summary_data, game_state)

    async def process_freeform(
        self,
        text: str,
        game_state: GameState,
        *,
        script_context: dict | None = None,
    ) -> FreeformResult | dict:
        for attempt in range(self._freeform_retries):
            try:
                return await asyncio.wait_for(
                    self._inner.process_freeform(text, game_state, script_context=script_context),
                    timeout=self._freeform_timeout,
                )
            except Exception as e:
                self._log_retry_failure("process_freeform", attempt + 1, self._freeform_retries, e)
                if attempt == self._freeform_retries - 1:
                    return parse_error("AI解析服务暂时不可用", PARSE_ERROR_TYPE_UNAVAILABLE)
        return parse_error("AI解析服务暂时不可用", PARSE_ERROR_TYPE_UNAVAILABLE)

    async def generate_minister_dialogue(
        self,
        minister: Minister,
        message: str,
        game_state: GameState,
        conversation_history: list[dict],
    ) -> dict:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.generate_minister_dialogue(minister, message, game_state, conversation_history),
                    timeout=self._timeout,
                )
            except Exception as e:
                self._log_retry_failure("generate_minister_dialogue", attempt + 1, self._retries, e)
                if attempt == self._retries - 1:
                    return await MockProvider().generate_minister_dialogue(
                        minister,
                        message,
                        game_state,
                        conversation_history,
                    )
        return await MockProvider().generate_minister_dialogue(minister, message, game_state, conversation_history)

