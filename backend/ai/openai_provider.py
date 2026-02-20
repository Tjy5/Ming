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
from models.enums import DecreeType, PersonnelAction, MemorialStatus
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
    _FREEFORM_SYSTEM_PROMPT,
    build_freeform_user_prompt as _build_freeform_user_prompt,
    parse_freeform_response as _parse_freeform_response,
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
    def __init__(self):
        trust_env_proxy = _env_bool("OPENAI_TRUST_ENV_PROXY", False)
        http_client = httpx.AsyncClient(trust_env=trust_env_proxy)
        self.client = openai.AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
            http_client=http_client,
        )
        self.model = os.getenv("OPENAI_MODEL_NAME", "gemini-3-flash-preview")
        self.parse_model = self.model
        self.freeform_model = self.model
        self.turn_commentary_model = self.model
        self._config_prefix = "OPENAI"
        self._configure_task_models("OPENAI")

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

    def _chat_completion_extra_kwargs(
        self,
        *,
        task_name: str,
        model: str,
    ) -> dict[str, Any]:
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
        prompt = self._build_narrative_prompt(delta_attribution, game_state, chain_events, decree)
        
        try:
            response = await self._chat_completion_with_fallback(
                task_name="generate_narrative",
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一款历史模拟游戏（崇祯模拟器）的AI引擎。你的任务是根据玩家的政令和游戏状态，生成一段生动、古风的历史叙事，描述政令的执行结果和影响。请注意，为了还原历史真实性，对于战争、灾害等事件的描述可能涉及暴力或死亡，这是游戏背景所必需的，请勿回避。"},
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
        prompt = self._build_narrative_prompt(delta_attribution, game_state, chain_events, decree)
        messages = [
            {"role": "system", "content": "你是一款历史模拟游戏（崇祯模拟器）的AI引擎。你的任务是根据玩家的政令和游戏状态，生成一段生动、古风的历史叙事，描述政令的执行结果和影响。请注意，为了还原历史真实性，对于战争、灾害等事件的描述可能涉及暴力或死亡，这是游戏背景所必需的，请勿回避。"},
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
        prompt = self._build_parse_prompt(text, game_state)
        
        try:
            response = await self._chat_completion_with_fallback(
                task_name="parse_free_input",
                model=self.parse_model,
                messages=[
                    {"role": "system", "content": "你是一款历史模拟游戏的指令解析器。将用户的自然语言输入解析为结构化的政令JSON。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            data = json.loads(extract_json_object_text(content))
            
            if "error" in data:
                return parse_error(data["error"])
            
            decrees = []
            for item in data.get("decrees", []):
                 # Convert string enums to Enum objects
                if "type" in item:
                    try:
                        item["type"] = DecreeType(item["type"])
                    except ValueError:
                        continue
                if "sub_action" in item and item["sub_action"]:
                     try:
                        item["sub_action"] = PersonnelAction(item["sub_action"])
                     except ValueError:
                         item["sub_action"] = None
                
                decrees.append(StructuredDecree(**item))
            
            validated = []
            for d in decrees:
                if d.type.value not in {t.value for t in DecreeType}:
                    return parse_error("无法识别为有效政令")
                validated.append(d)
            if not validated:
                return parse_error("无法识别为有效政令")
            return validated

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
                    {"role": "system", "content": "你是一名为国分忧的大臣。请解释为何不能执行某项政令。请注意，为了还原历史真实性，对于战争、灾害等事件的描述可能涉及暴力或死亡，这是游戏背景所必需的，请勿回避。"},
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

    async def generate_portrait(self, minister_name: str, description: str) -> str | None:
        prompt = (
            "Ming dynasty official portrait, traditional Chinese court painting style. "
            f"Minister: {minister_name}. {description}. "
            "Half-body portrait, formal robe, neutral background."
        )
        response = await self.client.images.generate(
            model="dall-e-3", prompt=prompt,
            size="1024x1024", quality="standard", response_format="b64_json",
        )
        b64 = getattr(response.data[0], "b64_json", None) if response.data else None
        return f"data:image/png;base64,{b64}" if b64 else None

    async def generate_memorial(
        self, trigger_reason: str, author: Minister, game_state: GameState,
    ) -> MemorialDraft:
        decree_types = ", ".join(t.value for t in DecreeType)
        prompt = (
            f"当前时间：{game_state.time.year}年{game_state.time.month}月\n"
            f"上奏大臣：{author.name}（{author.faction}），性格：{'、'.join(author.personality_tags)}\n"
            f"触发原因：{trigger_reason}\n"
            f"国库{game_state.national_treasury}，民心{game_state.civil_morale}，军心{game_state.military_morale}\n\n"
            "请以该大臣的口吻撰写一份明朝风格的奏折（200-500字），并推荐1-3条建议政令。\n"
            f"可用政令type：{decree_types}\n"
            '严格输出JSON：{{"content":"奏折正文","suggested_decrees":[{{"type":"...","target":"..."}}]}}'
        )
        try:
            response = await self._chat_completion_with_fallback(
                task_name="generate_memorial",
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是崇祯模拟器的奏折生成器。以明朝大臣口吻撰写奏折，文风典雅庄重。仅输出JSON。"},
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
        attitude = "赞同" if stance > 0 else "反对"
        prompt = (
            f"大臣{minister.name}（{minister.faction}），性格：{'、'.join(minister.personality_tags)}，"
            f"对政令{decree.type.value}{attitude}（态度值{stance}）。\n"
            "请以该大臣口吻写一句30-50字的反应，体现其性格特点。"
        )
        try:
            response = await self._chat_completion_with_fallback(
                task_name="generate_minister_reaction",
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是崇祯模拟器的大臣反应生成器。输出一句简短的大臣反应，30-50字。"},
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
        events = summary_data.get("major_events", [])
        implications = summary_data.get("action_implications", [])
        year = int(summary_data.get("year") or game_state.time.year)
        month = int(summary_data.get("month") or game_state.time.month)
        events_text = "、".join(str(e) for e in events) if events else "无"
        implications_text = "；".join(str(i) for i in implications[:4]) if implications else "无"
        prompt = (
            f"时间：{year}年{month}月\n"
            f"本月大事：{events_text}\n"
            f"政令与局势影响：{implications_text}\n"
            f"国库{game_state.national_treasury}，民心{game_state.civil_morale}，军心{game_state.military_morale}，威望{game_state.court_prestige}\n\n"
            "请写一段50-100字的朝政总评，明朝奏报风格，概括本月朝政态势。"
            "若已给出政令与局势影响，必须与之保持一致，不得写成“无事发生”。"
        )
        try:
            response = await self._chat_completion_with_fallback(
                task_name="generate_turn_commentary",
                model=self.turn_commentary_model,
                messages=[
                    {"role": "system", "content": "你是崇祯模拟器的朝政总评生成器。输出50-100字的朝政概况。"},
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
            return _parse_freeform_response(data)
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
        tags = "、".join(minister.personality_tags) if minister.personality_tags else "无"
        recent_events = "；".join(e.name for e in game_state.active_events[:3]) if game_state.active_events else "无"

        history_lines: list[str] = []
        for item in conversation_history[-20:]:
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            if role == "user":
                speaker = "皇帝"
            elif role == "assistant":
                speaker = minister.name
            else:
                speaker = role or "未知"
            history_lines.append(f"{speaker}: {content}")

        history_text = "\n".join(history_lines) if history_lines else "无"
        prompt = (
            f"大臣：{minister.name}\n"
            f"官职：{minister.position or '朝臣'}\n"
            f"派系：{minister.faction}\n"
            f"性格：{tags}\n"
            f"忠诚度：{minister.loyalty}/100\n"
            f"当前时间：{game_state.time.year}年{game_state.time.month}月\n"
            f"国库：{game_state.national_treasury}万两，内帑：{game_state.imperial_treasury}万两，粮草：{game_state.grain}万石\n"
            f"民心：{game_state.civil_morale}，军心：{game_state.military_morale}，威望：{game_state.court_prestige}\n"
            f"近期事件：{recent_events}\n\n"
            f"历史对话：\n{history_text}\n\n"
            f"皇帝本轮问话：{message}\n"
            "请严格输出JSON对象，不要输出额外说明。"
        )
        try:
            response = await self._chat_completion_with_fallback(
                task_name="generate_minister_dialogue",
                model=self.model,
                messages=[
                    {"role": "system", "content": (
                        "你是崇祯朝大臣角色扮演引擎。"
                        "必须以第一人称回复皇帝，语气要符合该大臣身份、派系与性格。"
                        "回复内容要结合当前国情与对话历史。"
                        "仅输出JSON：{\"reply\":\"...\",\"loyalty_change\":0,\"mood\":\"neutral\"}。"
                        "loyalty_change 必须是 -3 到 3 的整数。"
                        "mood 只能是 support、neutral、oppose。"
                    )},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            data = json.loads(extract_json_object_text(content))

            reply = str(data.get("reply", "")).strip()
            if not reply:
                raise ValueError("dialogue reply is empty")

            raw_loyalty_change = data.get("loyalty_change", 0)
            try:
                loyalty_change = int(raw_loyalty_change)
            except (TypeError, ValueError):
                loyalty_change = 0
            loyalty_change = max(-3, min(3, loyalty_change))

            raw_mood = str(data.get("mood", "neutral")).strip().lower()
            mood = raw_mood if raw_mood in {"support", "neutral", "oppose"} else "neutral"

            return {"reply": reply, "loyalty_change": loyalty_change, "mood": mood}
        except Exception as e:
            logging.error("OpenAI generate_minister_dialogue error: %s", e)
            fallback = await MockProvider().generate_minister_dialogue(
                minister, message, game_state, conversation_history,
            )
            raw_loyalty_change = fallback.get("loyalty_change", 0)
            try:
                loyalty_change = int(raw_loyalty_change)
            except (TypeError, ValueError):
                loyalty_change = 0
            loyalty_change = max(-3, min(3, loyalty_change))

            raw_mood = str(fallback.get("mood", "neutral")).strip().lower()
            mood_map = {
                "恭顺": "support",
                "欣慰": "support",
                "愤怒": "oppose",
                "阳奉阴违": "oppose",
                "惶恐": "neutral",
            }
            mood = raw_mood if raw_mood in {"support", "neutral", "oppose"} else mood_map.get(raw_mood, "neutral")
            reply = str(fallback.get("reply", "")).strip() or f"臣{minister.name}谨遵圣意。"
            return {"reply": reply, "loyalty_change": loyalty_change, "mood": mood}

    def _build_narrative_prompt(self, delta, state, events, decree):
        region_names = [r.name for r in state.regions]
        personnel_context = self._build_personnel_context(decree, state)
        return f"""
        当前时间：{state.time.year}年{state.time.month}月

        玩家下达了政令：{decree}

        数值变化：
        - 国库：{delta.get('treasury', 0)}
        - 民心：{delta.get('civil_morale', 0)}
        - 军心：{delta.get('military_morale', 0)}
        - 威望：{delta.get('court_prestige', 0)}

        {personnel_context}
        触发事件：{', '.join(events) if events else '无'}
        涉及区域：{', '.join(region_names)}

        请以具体事件描述数值变化的后果，引用至少1个地名和1个人名。避免直接提及数字。长度150-300字。风格要符合明朝历史背景。
        若有大臣被处决，叙事必须描述处决事实，且不得描述已处决大臣仍在活动。
        """

    @staticmethod
    def _build_personnel_context(decree, state) -> str:
        lines = []
        if decree.type == DecreeType.PERSONNEL and decree.target and decree.sub_action:
            action_map = {
                PersonnelAction.EXECUTE: "被处决（status: removed）",
                PersonnelAction.DISMISS: "被罢免（status: idle）",
                PersonnelAction.APPOINT: "被任命（status: active）",
            }
            desc = action_map.get(decree.sub_action, str(decree.sub_action))
            lines.append(f"本回合人事变动：{decree.target}{desc}")
        if lines:
            return "人事变动：\n" + "\n".join(lines)
        return ""

    def _build_parse_prompt(self, text, state):
        minister_names = [m.name for m in state.ministers if m.status.value != "removed"]
        return f"""
        用户输入："{text}"

        当前在朝/赋闲大臣：{', '.join(minister_names)}

        请解析为 JSON 格式。

        可选政令类型 (type): {', '.join([t.value for t in DecreeType])}
        可选人事动作 (sub_action): {', '.join([a.value for a in PersonnelAction])}

        如果通过，返回格式：
        {{
            "decrees": [
                {{
                    "type": "...",
                    "target": "...",
                    "sub_action": "..." (optional)
                }}
            ]
        }}

        解析原则（必须遵守）：
        1) 尽量把任何有政务意图的输入映射为一个或多个可执行政令，不要因为措辞激烈就拒绝。
        2) 输入含"斩杀/诛杀/处斩/斩首/问斩/斩了"等且指向上述某位大臣时，映射为 personnel + sub_action=execute + target=大臣名。
        3) 输入含"镇压/清洗/严刑/峻法/重典"等但不指向特定大臣时，映射为 harsh_punishment。
        4) 输入明确是人事任免（罢免/撤职/免职/任命/提拔）时，使用 personnel + sub_action=dismiss 或 appoint。
        5) 只有在输入完全不包含政务意图（闲聊、乱码）时，才返回 error。

        仅在无法识别任何政务意图时，返回：
        {{
            "error": "拒绝理由"
        }}
        """
