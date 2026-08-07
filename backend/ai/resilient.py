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
    get_rule_parse_fallback,
    parse_error,
)
from .fallbacks import (
    rule_chat_query,
    rule_classify_chat_intent,
    rule_classify_script_choice,
    rule_debate_speeches,
    rule_parse_free_input,
    rule_petitions,
    rule_script_trigger_decisions,
    rule_vote_tendency,
    template_action_implications,
    template_assembly_debate,
    template_memorial,
    template_minister_reaction,
    template_turn_commentary,
)
from .parsers import _validate_decrees


async def _local_rule_parse(
    text: str,
    game_state: GameState,
) -> list[StructuredDecree] | None:
    fallback = rule_parse_free_input(text, game_state)
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

    @staticmethod
    def _normalize_script_choice_result(result: dict) -> dict:
        if "error" in result:
            return result

        raw_index = result.get("choice_index")
        if raw_index is None or isinstance(raw_index, bool):
            choice_index = None
        else:
            try:
                choice_index = int(raw_index)
            except (TypeError, ValueError):
                choice_index = None

        raw_confidence = result.get("confidence", 0.0)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        reason = str(result.get("reason", "")).strip() or "AI未提供分类理由"
        return {
            "choice_index": choice_index,
            "confidence": confidence,
            "reason": reason,
        }

    @staticmethod
    def _normalize_chat_intent_result(result: dict) -> dict:
        if "error" in result:
            return result

        intent = str(result.get("intent", "")).strip().lower()
        if intent not in {"query", "execute", "advance_month"}:
            intent = "execute"

        raw_confidence = result.get("confidence", 0.0)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        reason = str(result.get("reason", "")).strip() or "AI未提供分类理由"
        return {
            "intent": intent,
            "confidence": confidence,
            "reason": reason,
        }

    @staticmethod
    def _normalize_script_trigger_decisions(
        result: dict,
        candidate_ids: set[str],
    ) -> dict[str, tuple[bool, str]] | dict:
        if "error" in result:
            return result

        normalized: dict[str, tuple[bool, str]] = {}
        for key, value in result.items():
            script_id = str(key).strip()
            if script_id not in candidate_ids:
                continue
            if isinstance(value, tuple) and len(value) >= 2:
                normalized[script_id] = (bool(value[0]), str(value[1]).strip() or "AI未给出理由")
                continue
            if isinstance(value, list) and len(value) >= 2:
                normalized[script_id] = (bool(value[0]), str(value[1]).strip() or "AI未给出理由")
                continue
            if isinstance(value, dict):
                normalized[script_id] = (
                    bool(value.get("should_trigger", True)),
                    str(value.get("reason", "")).strip() or "AI未给出理由",
                )
                continue
            if isinstance(value, bool):
                normalized[script_id] = (value, "AI未给出理由")

        for script_id in candidate_ids:
            normalized.setdefault(script_id, (True, "AI未返回该事件决策，默认触发"))
        return normalized

    async def generate_narrative(
        self,
        delta_attribution: dict,
        game_state: GameState,
        chain_events: list[str],
        decree: StructuredDecree,
        *,
        fix_instruction: str | None = None,
    ) -> str:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.generate_narrative(
                        delta_attribution, game_state, chain_events, decree,
                        fix_instruction=fix_instruction,
                    ),
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
                    return template_memorial(trigger_reason, author, game_state)
        return template_memorial(trigger_reason, author, game_state)

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
                    return template_minister_reaction(minister, decree, stance, game_state)
        return template_minister_reaction(minister, decree, stance, game_state)

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
                    return rule_petitions(participants)
        return rule_petitions(participants)

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
                    return rule_debate_speeches(topic, participants, game_state)
        return rule_debate_speeches(topic, participants, game_state)

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
                    return rule_vote_tendency(minister, decree_type, game_state)
        return rule_vote_tendency(minister, decree_type, game_state)

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
        return template_action_implications(summary_data, game_state)

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
                    return template_turn_commentary(summary_data, game_state)
        return template_turn_commentary(summary_data, game_state)

    async def classify_script_choice(
        self,
        player_text: str,
        script_context: dict | None = None,
        *,
        game_state: GameState | None = None,
    ) -> dict:
        for attempt in range(self._parse_retries):
            try:
                result = await asyncio.wait_for(
                    self._inner.classify_script_choice(
                        player_text,
                        script_context,
                        game_state=game_state,
                    ),
                    timeout=self._parse_timeout,
                )
                if not isinstance(result, dict):
                    raise ValueError("脚本选项分类返回格式无效")
                normalized = self._normalize_script_choice_result(result)
                if "error" in normalized:
                    raise ValueError(str(normalized.get("error", "脚本选项分类失败")))
                return normalized
            except Exception as e:
                self._log_retry_failure("classify_script_choice", attempt + 1, self._parse_retries, e)
                if attempt == self._parse_retries - 1:
                    break

        try:
            fallback = await rule_classify_script_choice(player_text, script_context)
            if isinstance(fallback, dict):
                normalized = self._normalize_script_choice_result(fallback)
                if "error" not in normalized:
                    return normalized
        except Exception as e:
            self._log_retry_failure("classify_script_choice_fallback", 1, 1, e)

        return {
            "choice_index": None,
            "confidence": 0.0,
            "reason": "脚本选项分类不可用",
        }

    async def select_script_trigger_decisions(
        self,
        game_state: GameState,
        candidates: list[dict],
    ) -> dict[str, tuple[bool, str]]:
        candidate_ids = {
            str(item.get("script_id", "")).strip()
            for item in candidates
            if isinstance(item, dict) and str(item.get("script_id", "")).strip()
        }
        if not candidate_ids:
            return {}

        for attempt in range(self._parse_retries):
            try:
                result = await asyncio.wait_for(
                    self._inner.select_script_trigger_decisions(game_state, candidates),
                    timeout=self._parse_timeout,
                )
                if not isinstance(result, dict):
                    raise ValueError("剧情触发决策返回格式无效")
                normalized = self._normalize_script_trigger_decisions(result, candidate_ids)
                if "error" in normalized:
                    raise ValueError(str(normalized.get("error", "剧情触发决策失败")))
                return normalized
            except Exception as e:
                self._log_retry_failure(
                    "select_script_trigger_decisions",
                    attempt + 1,
                    self._parse_retries,
                    e,
                )
                if attempt == self._parse_retries - 1:
                    break

        try:
            fallback = rule_script_trigger_decisions(game_state, candidates)
            normalized = self._normalize_script_trigger_decisions(fallback, candidate_ids)
            if "error" not in normalized:
                return normalized
        except Exception as e:
            self._log_retry_failure("select_script_trigger_decisions_fallback", 1, 1, e)

        return {
            script_id: (True, "AI不可用，回退规则触发")
            for script_id in candidate_ids
        }

    async def classify_chat_intent(
        self,
        text: str,
        game_state: GameState,
        conversation_history: list[dict],
    ) -> dict:
        for attempt in range(self._parse_retries):
            try:
                result = await asyncio.wait_for(
                    self._inner.classify_chat_intent(text, game_state, conversation_history),
                    timeout=self._parse_timeout,
                )
                if not isinstance(result, dict):
                    raise ValueError("聊天意图分类返回格式无效")
                normalized = self._normalize_chat_intent_result(result)
                if "error" in normalized:
                    raise ValueError(str(normalized.get("error", "聊天意图分类失败")))
                return normalized
            except Exception as e:
                self._log_retry_failure("classify_chat_intent", attempt + 1, self._parse_retries, e)
                if attempt == self._parse_retries - 1:
                    break

        try:
            fallback = rule_classify_chat_intent(text, game_state, conversation_history)
            if isinstance(fallback, dict):
                normalized = self._normalize_chat_intent_result(fallback)
                if "error" not in normalized:
                    return normalized
        except Exception as e:
            self._log_retry_failure("classify_chat_intent_fallback", 1, 1, e)

        return {
            "intent": "execute",
            "confidence": 0.0,
            "reason": "聊天意图分类不可用",
        }

    async def chat_query(
        self,
        text: str,
        game_state: GameState,
        conversation_history: list[dict],
    ) -> str:
        for attempt in range(self._retries):
            try:
                reply = await asyncio.wait_for(
                    self._inner.chat_query(text, game_state, conversation_history),
                    timeout=self._timeout,
                )
                content = str(reply).strip()
                if not content:
                    raise ValueError("chat_query returned empty content")
                return content
            except Exception as e:
                self._log_retry_failure("chat_query", attempt + 1, self._retries, e)
                if attempt == self._retries - 1:
                    raise

        raise RuntimeError("chat_query failed")

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
                    raise
        raise RuntimeError("generate_minister_dialogue failed")
