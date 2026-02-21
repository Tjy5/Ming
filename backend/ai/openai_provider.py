from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
import openai
from dotenv import load_dotenv

from models.game import GameState, StructuredDecree, Minister, DebateResult, FreeformResult, MinisterReaction, MemorialDraft
from models.enums import MemorialStatus
from .provider import (
    AIProvider,
    MockProvider,
    PARSE_ERROR_TYPE_UNAVAILABLE,
    parse_error,
    build_debate_prompt,
    DEBATE_SYSTEM_PROMPT,
    parse_debate_response,
    extract_json_object_text,
    validate_memorial_decrees,
    parse_memorial_draft,
    parse_decree_response,
    _FREEFORM_SYSTEM_PROMPT,
    build_freeform_user_prompt as _build_freeform_user_prompt,
    parse_freeform_response as _parse_freeform_response,
)
from .prompts import (
    MEMORIAL_SYSTEM_PROMPT,
    MINISTER_DIALOGUE_SYSTEM_PROMPT,
    MINISTER_REACTION_SYSTEM_PROMPT,
    NARRATIVE_SYSTEM_PROMPT,
    PARSE_SYSTEM_PROMPT,
    REJECTION_SYSTEM_PROMPT,
    TURN_COMMENTARY_SYSTEM_PROMPT,
    build_memorial_prompt,
    build_minister_dialogue_prompt,
    build_minister_reaction_prompt,
    build_narrative_prompt as _build_narrative_prompt,
    build_parse_prompt as _build_parse_prompt,
    build_turn_commentary_prompt,
    normalize_dialogue_fallback_payload,
    normalize_dialogue_payload,
)

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_str(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _env_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class OpenAIProvider(AIProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        prefix: str = "OPENAI",
    ):
        trust_env_proxy = _env_bool(f"{prefix}_TRUST_ENV_PROXY", False)
        if not trust_env_proxy and prefix != "OPENAI":
            trust_env_proxy = _env_bool("OPENAI_TRUST_ENV_PROXY", False)
            
        http_client = httpx.AsyncClient(trust_env=trust_env_proxy)
        
        actual_api_key = api_key or os.getenv(f"{prefix}_API_KEY")
        actual_base_url = base_url or os.getenv(f"{prefix}_BASE_URL")
        actual_model = model or os.getenv(f"{prefix}_MODEL_NAME") or os.getenv(f"{prefix}_MODEL", "gemini-3-flash-preview")

        self.client = openai.AsyncOpenAI(
            api_key=actual_api_key,
            base_url=actual_base_url,
            http_client=http_client,
        )
        self.model = actual_model
        self.parse_model = self.model
        self.freeform_model = self.model
        self.turn_commentary_model = self.model
        self._config_prefix = prefix
        self._enable_thinking = _env_bool(f"{prefix}_ENABLE_THINKING", False)
        self._enable_thinking_simple = _env_bool(f"{prefix}_ENABLE_THINKING_SIMPLE", False)
        self._configure_task_models(prefix)

    def _configure_task_models(
        self,
        prefix: str,
        *,
        parse_default: str | None = None,
        freeform_default: str | None = None,
        turn_commentary_default: str | None = None,
        use_simple_for_parse: bool = True,
        use_simple_for_freeform: bool = True,
        use_simple_for_turn_commentary: bool = True,
    ) -> None:
        self._config_prefix = prefix
        simple_model = _env_str(f"{prefix}_SIMPLE_MODEL")
        parse_simple = simple_model if use_simple_for_parse else None
        freeform_simple = simple_model if use_simple_for_freeform else None
        turn_commentary_simple = simple_model if use_simple_for_turn_commentary else None

        self.parse_model = (
            _env_str(f"{prefix}_PARSE_MODEL")
            or parse_simple
            or parse_default
            or self.model
        )
        self.freeform_model = (
            _env_str(f"{prefix}_FREEFORM_MODEL")
            or freeform_simple
            or freeform_default
            or self.model
        )
        self.turn_commentary_model = (
            _env_str(f"{prefix}_TURN_COMMENTARY_MODEL")
            or turn_commentary_simple
            or turn_commentary_default
            or self.model
        )

    def _thinking_config_from_env(self, env_name: str) -> dict[str, Any] | None:
        raw = _env_str(env_name)
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            logging.warning("Ignore invalid %s JSON: %s", env_name, exc)
            return None
        if not isinstance(payload, dict):
            logging.warning("Ignore non-object %s JSON payload", env_name)
            return None
        return payload

    def _chat_completion_extra_kwargs(
        self,
        *,
        task_name: str,
        model: str,
    ) -> dict[str, Any]:
        simple_model = getattr(self, "parse_model", None)
        is_simple = model and simple_model and model == simple_model and model != self.model

        thinking_env = (
            f"{self._config_prefix}_THINKING_CONFIG_SIMPLE"
            if is_simple
            else f"{self._config_prefix}_THINKING_CONFIG"
        )
        thinking_config = self._thinking_config_from_env(thinking_env)
        if thinking_config is None and is_simple:
            thinking_config = self._thinking_config_from_env(
                f"{self._config_prefix}_THINKING_CONFIG",
            )
        if thinking_config is not None:
            # Extract reasoning_effort as top-level parameter for OpenAI API
            result: dict[str, Any] = {}
            if "reasoning_effort" in thinking_config:
                result["reasoning_effort"] = thinking_config["reasoning_effort"]
                # Remove reasoning_effort from extra_body
                remaining_config = {k: v for k, v in thinking_config.items() if k != "reasoning_effort"}
                if remaining_config:
                    result["extra_body"] = remaining_config
            else:
                result["extra_body"] = thinking_config
            return result

        enable = self._enable_thinking_simple if is_simple else self._enable_thinking
        if enable:
            return {"extra_body": {"enable_thinking": True}}
        return {}

    def _env_sampling_value(
        self,
        *,
        task_name: str,
        key: str,
    ) -> float | None:
        task_key = task_name.upper()
        candidates = (
            f"{self._config_prefix}_{task_key}_{key}",
            f"AI_{task_key}_{key}",
            f"{self._config_prefix}_{key}",
            f"AI_{key}",
        )
        for env_name in candidates:
            value = _env_float(env_name)
            if value is not None:
                return value
        return None

    @staticmethod
    def _validate_temperature(value: float | None) -> float | None:
        if value is None:
            return None
        if 0.0 <= value <= 2.0:
            return value
        return None

    @staticmethod
    def _validate_top_p(value: float | None) -> float | None:
        if value is None:
            return None
        if 0.0 < value <= 1.0:
            return value
        return None

    def _resolve_sampling_params(
        self,
        *,
        task_name: str,
        default_temperature: float,
        default_top_p: float | None,
    ) -> tuple[float, float | None]:
        env_temperature = self._env_sampling_value(
            task_name=task_name,
            key="TEMPERATURE",
        )
        env_top_p = self._env_sampling_value(
            task_name=task_name,
            key="TOP_P",
        )

        temperature = self._validate_temperature(env_temperature)
        if temperature is None:
            if env_temperature is not None:
                logging.warning(
                    "Ignore invalid %s temperature %.3f; keep default %.3f",
                    task_name,
                    env_temperature,
                    default_temperature,
                )
            temperature = default_temperature

        top_p = self._validate_top_p(env_top_p)
        if env_top_p is not None and top_p is None:
            logging.warning(
                "Ignore invalid %s top_p %.3f; keep default",
                task_name,
                env_top_p,
            )
            top_p = default_top_p
        elif top_p is None:
            top_p = default_top_p

        return temperature, top_p

    def _build_chat_completion_kwargs(
        self,
        *,
        task_name: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        top_p: float | None = None,
        response_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        resolved_temperature, resolved_top_p = self._resolve_sampling_params(
            task_name=task_name,
            default_temperature=temperature,
            default_top_p=top_p,
        )
        kwargs: dict[str, Any] = {
            "messages": messages,
            "temperature": resolved_temperature,
        }
        if resolved_top_p is not None:
            kwargs["top_p"] = resolved_top_p
        if response_format is not None:
            kwargs["response_format"] = response_format
        kwargs.update(
            self._chat_completion_extra_kwargs(task_name=task_name, model=model),
        )
        return kwargs

    async def _chat_completion_with_fallback(
        self,
        *,
        task_name: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        top_p: float | None = None,
        response_format: dict[str, str] | None = None,
    ) -> Any:
        kwargs = self._build_chat_completion_kwargs(
            task_name=task_name,
            model=model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            response_format=response_format,
        )

        try:
            return await self.client.chat.completions.create(
                model=model,
                **kwargs,
            )
        except Exception as first_error:
            if model == self.model:
                raise
            logging.warning(
                "%s model %s failed (%s), fallback to %s",
                task_name,
                model,
                type(first_error).__name__,
                self.model,
            )
            fallback_kwargs = self._build_chat_completion_kwargs(
                task_name=task_name,
                model=self.model,
                messages=messages,
                temperature=temperature,
                top_p=top_p,
                response_format=response_format,
            )
            return await self.client.chat.completions.create(
                model=self.model,
                **fallback_kwargs,
            )

    async def generate_narrative(
        self, delta_attribution: dict, game_state: GameState,
        chain_events: list[str], decree: StructuredDecree,
    ) -> str:
        prompt = _build_narrative_prompt(delta_attribution, game_state, chain_events, decree)
        
        try:
            response = await self._chat_completion_with_fallback(
                task_name="generate_narrative",
                model=self.model,
                messages=[
                    {"role": "system", "content": NARRATIVE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.error(f"Error generating narrative: {e}")
            return "（AI服务响应异常，但政令已执行）"

    @staticmethod
    def _stream_chunk_text(chunk: Any) -> str:
        choices = getattr(chunk, "choices", None)
        if not choices:
            return ""
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            return ""
        content = getattr(delta, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
                    continue
                if isinstance(item, dict):
                    value = item.get("text")
                    if isinstance(value, str):
                        parts.append(value)
            return "".join(parts)
        return ""

    async def stream_narrative(
        self, delta_attribution: dict, game_state: GameState,
        chain_events: list[str], decree: StructuredDecree,
    ) -> AsyncIterator[str]:
        prompt = _build_narrative_prompt(delta_attribution, game_state, chain_events, decree)
        messages = [
            {"role": "system", "content": NARRATIVE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        kwargs = self._build_chat_completion_kwargs(
            task_name="generate_narrative",
            model=self.model,
            messages=messages,
            temperature=0.7,
        )
        emitted_any = False
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                text = self._stream_chunk_text(chunk)
                if text:
                    emitted_any = True
                    yield text
            return
        except Exception as e:
            logging.error("Error streaming narrative: %s", e)
        if emitted_any:
            return
        fallback = await self.generate_narrative(
            delta_attribution, game_state, chain_events, decree,
        )
        if fallback:
            yield fallback

    async def parse_free_input(
        self, text: str, game_state: GameState,
    ) -> list[StructuredDecree] | dict:
        prompt = _build_parse_prompt(text, game_state)
        
        try:
            response = await self._chat_completion_with_fallback(
                task_name="parse_free_input",
                model=self.parse_model,
                messages=[
                    {"role": "system", "content": PARSE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            data = json.loads(extract_json_object_text(content))
            return parse_decree_response(data)

        except json.JSONDecodeError as e:
            logging.error(f"Error parsing LLM JSON output: {e}")
            return parse_error("AI返回格式异常，请重试")
        except Exception as e:
            logging.error(f"Error parsing input: {e}")
            return parse_error(
                "AI解析服务暂时不可用，请使用按钮操作",
                PARSE_ERROR_TYPE_UNAVAILABLE,
            )

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        prompt = f"玩家试图执行以下政令，但被系统拒绝（原有：{reason}）。请以大臣劝谏的口吻，委婉但坚定地告知陛下为何不能执行。\n\n政令：{decree}"
        try:
            response = await self._chat_completion_with_fallback(
                task_name="rejection_narrative",
                model=self.model,
                messages=[
                    {"role": "system", "content": REJECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return f"陛下，此令行不通：{reason}"

    async def generate_debate_narrative(
        self, topic: str, minister_a: Minister, minister_b: Minister, game_state: GameState,
    ) -> DebateResult | None:
        prompt = build_debate_prompt(topic, minister_a, minister_b, game_state)
        response = await self._chat_completion_with_fallback(
            task_name="generate_debate_narrative",
            model=self.model,
            messages=[
                {"role": "system", "content": DEBATE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            response_format={"type": "json_object"},
        )
        content = (response.choices[0].message.content or "").strip()
        if not content:
            return None
        payload = json.loads(extract_json_object_text(content))
        return parse_debate_response(payload, minister_a, minister_b)



    async def generate_memorial(
        self, trigger_reason: str, author: Minister, game_state: GameState,
    ) -> MemorialDraft:
        prompt = build_memorial_prompt(trigger_reason, author, game_state)
        try:
            response = await self._chat_completion_with_fallback(
                task_name="generate_memorial",
                model=self.model,
                messages=[
                    {"role": "system", "content": MEMORIAL_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            draft = parse_memorial_draft(
                response.choices[0].message.content or "", author.name, game_state,
            )
            if not draft.suggested_decrees and trigger_reason.split(":", 1)[0] != "faction_crisis":
                mock = await MockProvider().generate_memorial(trigger_reason, author, game_state)
                draft.suggested_decrees = mock.suggested_decrees
            return draft
        except Exception as e:
            logging.error("OpenAIProvider generate_memorial fallback: %s", e)
            return await MockProvider().generate_memorial(trigger_reason, author, game_state)

    async def generate_minister_reaction(
        self, minister: Minister, decree: StructuredDecree, stance: int, game_state: GameState,
    ) -> str:
        prompt = build_minister_reaction_prompt(minister, decree, stance)
        try:
            response = await self._chat_completion_with_fallback(
                task_name="generate_minister_reaction",
                model=self.model,
                messages=[
                    {"role": "system", "content": MINISTER_REACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.error(f"generate_minister_reaction error: {e}")
            raise

    async def generate_assembly_debate(
        self, topic: str, participants: list[Minister], game_state: GameState,
    ) -> dict | None:
        parts = [f"议题：{topic}\n当前国情：{game_state.time.year}年{game_state.time.month}月，"
                 f"国库{game_state.national_treasury}，民心{game_state.civil_morale}，军心{game_state.military_morale}\n\n参与大臣："]
        for p in participants:
            parts.append(f"- {p.name}（{p.faction}），性格：{'、'.join(p.personality_tags)}，"
                         f"文治{p.abilities.civil}/武略{p.abilities.military}")
        prompt = "\n".join(parts)
        try:
            response = await self._chat_completion_with_fallback(
                task_name="generate_assembly_debate",
                model=self.model,
                messages=[
                    {"role": "system", "content": (
                        "你是崇祯模拟器的朝会辩论生成器。输出JSON：{"
                        "\"debate_text\":\"300-500字多人对话\","
                        "\"participants\":[{\"name\":\"...\",\"position\":\"...\",\"argument_text\":\"...\"}],"
                        "\"suggestions\":[{\"title\":\"...\",\"description\":\"...\",\"decree_type\":\"...\",\"supporter_names\":[]}],"
                        "\"consensus\":\"共识描述\"}"
                    )},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                return None
            return json.loads(extract_json_object_text(content))
        except Exception as e:
            logging.error(f"generate_assembly_debate error: {e}")
            raise

    async def generate_turn_commentary(
        self, summary_data: dict, game_state: GameState,
    ) -> str:
        prompt = build_turn_commentary_prompt(summary_data, game_state)
        try:
            response = await self._chat_completion_with_fallback(
                task_name="generate_turn_commentary",
                model=self.turn_commentary_model,
                messages=[
                    {"role": "system", "content": TURN_COMMENTARY_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.error(f"generate_turn_commentary error: {e}")
            raise

    async def process_freeform(
        self, text: str, game_state: GameState,
        *, script_context: dict | None = None,
    ) -> FreeformResult | dict:
        prompt = _build_freeform_user_prompt(text, game_state, script_context)
        try:
            response = await self._chat_completion_with_fallback(
                task_name="process_freeform",
                model=self.freeform_model,
                messages=[
                    {"role": "system", "content": _FREEFORM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            data = json.loads(extract_json_object_text(content))
            return _parse_freeform_response(data, game_state.time.year, game_state.time.month)
        except json.JSONDecodeError as e:
            logging.error(f"OpenAI freeform JSON parse error: {e}")
            return parse_error("AI返回格式异常", PARSE_ERROR_TYPE_UNAVAILABLE)
        except Exception as e:
            logging.error(f"OpenAI process_freeform error: {e}")
            return parse_error("AI服务暂时不可用", PARSE_ERROR_TYPE_UNAVAILABLE)

    async def generate_minister_dialogue(
        self, minister: Minister, message: str, game_state: GameState,
        conversation_history: list[dict],
    ) -> dict:
        prompt = build_minister_dialogue_prompt(
            minister=minister,
            message=message,
            game_state=game_state,
            conversation_history=conversation_history,
        )
        try:
            response = await self._chat_completion_with_fallback(
                task_name="generate_minister_dialogue",
                model=self.model,
                messages=[
                    {"role": "system", "content": MINISTER_DIALOGUE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            data = json.loads(extract_json_object_text(content))
            return normalize_dialogue_payload(data)
        except Exception as e:
            logging.error("OpenAI generate_minister_dialogue error: %s", e)
            fallback = await MockProvider().generate_minister_dialogue(
                minister, message, game_state, conversation_history,
            )
            return normalize_dialogue_fallback_payload(fallback, minister)
