from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any, Mapping

import httpx

from anthropic import AsyncAnthropic

from models.game import GameState, StructuredDecree, Minister, DebateResult, FreeformResult, MinisterReaction, MemorialDraft
from models.enums import DecreeType, MemorialStatus, MinisterStatus
from .fallbacks import template_assembly_debate, template_memorial
from .base import GenerationResult
from .errors import log_safe_provider_exception
from .provider import (
    AIProvider,
    PARSE_ERROR_TYPE_UNAVAILABLE,
    parse_error,
    build_debate_prompt,
    build_script_choice_classification_prompt,
    build_script_trigger_selection_prompt,
    DEBATE_SYSTEM_PROMPT,
    SCRIPT_CHOICE_CLASSIFICATION_SYSTEM_PROMPT,
    SCRIPT_TRIGGER_SELECTION_SYSTEM_PROMPT,
    parse_debate_response,
    parse_script_choice_classification_response,
    parse_script_trigger_selection_response,
    extract_json_object_text,
    validate_memorial_decrees,
    parse_memorial_draft,
    parse_decree_response,
    _FREEFORM_SYSTEM_PROMPT,
    build_freeform_user_prompt as _build_freeform_user_prompt,
    parse_freeform_response as _parse_freeform_response,
    infer_decree_type_from_topic,
)
from .prompts import (
    CHAT_CLASSIFY_PROMPT,
    CHAT_QUERY_PROMPT,
    MEMORIAL_SYSTEM_PROMPT,
    MINISTER_DIALOGUE_SYSTEM_PROMPT,
    MINISTER_REACTION_SYSTEM_PROMPT,
    NARRATIVE_SYSTEM_PROMPT,
    PARSE_SYSTEM_PROMPT,
    REJECTION_SYSTEM_PROMPT,
    TURN_COMMENTARY_SYSTEM_PROMPT,
    build_chat_classify_prompt,
    build_chat_query_prompt,
    build_memorial_prompt,
    build_minister_dialogue_prompt,
    build_minister_reaction_prompt,
    build_narrative_prompt as _build_narrative_prompt,
    build_parse_prompt as _build_parse_prompt,
    build_turn_commentary_prompt,
    normalize_chat_intent_payload,
    normalize_dialogue_payload,
)

logger = logging.getLogger(__name__)


class AnthropicProvider(AIProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        prefix: str = "ANTHROPIC",
        simple_model: str | None = None,
        enable_thinking: bool | None = None,
        enable_thinking_simple: bool | None = None,
        thinking_config: Mapping[str, Any] | None = None,
        thinking_config_simple: Mapping[str, Any] | None = None,
        http_client: httpx.AsyncClient | None = None,
        sdk_max_retries: int | None = None,
        use_environment: bool = True,
    ):
        self._use_environment = use_environment
        if use_environment:
            actual_api_key = api_key or os.getenv(f"{prefix}_API_KEY")
            actual_base_url = base_url or os.getenv(f"{prefix}_BASE_URL") or ""
            actual_model = (
                model
                or os.getenv(f"{prefix}_MODEL_NAME")
                or os.getenv(f"{prefix}_MODEL")
                or "claude-3-5-sonnet-latest"
            )
        else:
            actual_api_key = api_key
            actual_base_url = base_url or ""
            actual_model = model

        kwargs = {}
        if actual_api_key:
            kwargs["api_key"] = actual_api_key
        if actual_base_url:
            kwargs["base_url"] = actual_base_url
        if http_client is not None:
            kwargs["http_client"] = http_client
        if sdk_max_retries is not None:
            kwargs["max_retries"] = max(0, sdk_max_retries)

        self.client = AsyncAnthropic(**kwargs)
        self.model = actual_model
        self.simple_model = simple_model
        self._explicit_thinking_config = dict(thinking_config) if thinking_config is not None else None
        self._thinking_config = self._load_thinking_config(prefix)

    def _load_thinking_config(self, prefix: str) -> dict[str, object] | None:
        env_name = f"{prefix}_THINKING_CONFIG"
        if not self._use_environment:
            payload = self._explicit_thinking_config
            if payload is None:
                return None
        else:
            raw_config = (os.getenv(env_name) or "").strip()
            if not raw_config:
                return None
            try:
                payload = json.loads(raw_config)
            except json.JSONDecodeError as exc:
                log_safe_provider_exception(
                    logger,
                    stage="load_thinking_config",
                    exc=exc,
                    level=logging.WARNING,
                )
                return None
        if not isinstance(payload, dict):
            logging.warning("Ignore non-object %s payload", env_name)
            return None
        return payload

    async def _messages_create(self, **kwargs):
        if self._thinking_config is not None:
            kwargs["thinking"] = self._thinking_config
        return await self.client.messages.create(**kwargs)

    def _messages_stream(self, **kwargs):
        if self._thinking_config is not None:
            kwargs["thinking"] = self._thinking_config
        return self.client.messages.stream(**kwargs)

    async def generate_text_once(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_output_tokens: int = 128,
        response_json: bool = False,
    ) -> GenerationResult:
        system = system_prompt or "Return only the requested content."
        if response_json:
            system = f"{system}\nReturn one valid JSON object and no markdown."
        response = await self._messages_create(
            model=self.model,
            max_tokens=max(1, max_output_tokens),
            system=system,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        text = "".join(
            str(getattr(block, "text", ""))
            for block in response.content
            if getattr(block, "type", "") == "text"
        ).strip()
        if not text:
            raise ValueError("provider returned empty generation content")
        usage = getattr(response, "usage", None)
        return GenerationResult(
            text=text,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            provider_request_id=getattr(response, "_request_id", None),
        )

    async def aclose(self) -> None:
        await self.client.close()


    @staticmethod
    def _load_json_payload(text: str) -> dict | list | None:
        content = (text or "").strip()
        if not content:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            try:
                return json.loads(extract_json_object_text(content))
            except Exception:
                return None

    @staticmethod
    def _normalize_urgency(value: str) -> str:
        raw = (value or "").strip()
        if raw in {"高", "中", "低"}:
            return raw
        mapping = {"high": "高", "medium": "中", "low": "低"}
        return mapping.get(raw.lower(), "中")

    @staticmethod
    def _normalize_stance(value: str) -> str:
        raw = (value or "").strip()
        if raw in {"赞成", "反对", "中立"}:
            return raw
        mapping = {
            "support": "赞成",
            "oppose": "反对",
            "neutral": "中立",
            "abstain": "中立",
        }
        return mapping.get(raw.lower(), "中立")

    async def generate_narrative(
        self, delta_attribution: dict, game_state: GameState,
        chain_events: list[str], decree: StructuredDecree,
        *, fix_instruction: str | None = None,
    ) -> str:
        prompt = _build_narrative_prompt(delta_attribution, game_state, chain_events, decree)
        if fix_instruction:
            prompt = f"{prompt}\n\n{fix_instruction}"

        try:
            response = await self._messages_create(
                model=self.model,
                max_tokens=2048,
                system=NARRATIVE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            return response.content[0].text.strip()
        except Exception as e:
            log_safe_provider_exception(logger, stage="generate_narrative", exc=e)
            return "（AI服务响应异常，但政令已执行）"

    async def stream_narrative(
        self, delta_attribution: dict, game_state: GameState,
        chain_events: list[str], decree: StructuredDecree,
    ) -> AsyncIterator[str]:
        prompt = _build_narrative_prompt(delta_attribution, game_state, chain_events, decree)
        
        try:
            async with self._messages_stream(
                model=self.model,
                max_tokens=2048,
                system=NARRATIVE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield text
        except Exception as e:
            log_safe_provider_exception(logger, stage="stream_narrative", exc=e)
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
            response = await self._messages_create(
                model=self.model,
                max_tokens=2048,
                system=PARSE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            content = response.content[0].text.strip()
            data = json.loads(extract_json_object_text(content))
            return parse_decree_response(data)

        except json.JSONDecodeError as e:
            log_safe_provider_exception(logger, stage="parse_free_input_json", exc=e)
            return parse_error("AI返回格式异常，请重试")
        except Exception as e:
            log_safe_provider_exception(logger, stage="parse_free_input", exc=e)
            return parse_error(
                "AI解析服务暂时不可用，请使用按钮操作",
                PARSE_ERROR_TYPE_UNAVAILABLE,
            )

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        prompt = f"玩家试图执行以下政令，但被系统拒绝（原有：{reason}）。请以大臣劝谏的口吻，委婉但坚定地告知主公为何不能执行。\n\n政令：{decree}"
        try:
            response = await self._messages_create(
                model=self.model,
                max_tokens=1024,
                system=REJECTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            return response.content[0].text.strip()
        except Exception:
            return f"主公，此令行不通：{reason}"

    async def generate_debate_narrative(
        self, topic: str, minister_a: Minister, minister_b: Minister, game_state: GameState,
    ) -> DebateResult | None:
        prompt = build_debate_prompt(topic, minister_a, minister_b, game_state)
        try:
            response = await self._messages_create(
                model=self.model,
                max_tokens=2048,
                system=DEBATE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
            )
            content = response.content[0].text.strip()
            if not content:
                return None
            payload = json.loads(extract_json_object_text(content))
            return parse_debate_response(payload, minister_a, minister_b)
        except Exception as e:
            log_safe_provider_exception(logger, stage="generate_debate_narrative", exc=e)
            return None



    async def generate_memorial(
        self, trigger_reason: str, author: Minister, game_state: GameState,
    ) -> MemorialDraft:
        prompt = build_memorial_prompt(trigger_reason, author, game_state)
        try:
            response = await self._messages_create(
                model=self.model,
                max_tokens=2048,
                system=MEMORIAL_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            draft = parse_memorial_draft(response.content[0].text or "", author.name, game_state)
            if not draft.suggested_decrees and trigger_reason.split(":", 1)[0] != "faction_crisis":
                fallback = template_memorial(trigger_reason, author, game_state)
                draft.suggested_decrees = fallback.suggested_decrees
            return draft
        except Exception as e:
            log_safe_provider_exception(logger, stage="generate_memorial", exc=e)
            return template_memorial(trigger_reason, author, game_state)

    async def generate_minister_reaction(
        self, minister: Minister, decree: StructuredDecree, stance: int, game_state: GameState,
    ) -> str:
        prompt = build_minister_reaction_prompt(minister, decree, stance)
        try:
            response = await self._messages_create(
                model=self.model,
                max_tokens=1024,
                system=MINISTER_REACTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
            )
            return response.content[0].text.strip()
        except:
            return ""

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
            response = await self._messages_create(
                model=self.model,
                max_tokens=1024,
                system=MINISTER_DIALOGUE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
            )
            content = response.content[0].text.strip()
            data = json.loads(extract_json_object_text(content))
            return normalize_dialogue_payload(data)
        except Exception as e:
            log_safe_provider_exception(logger, stage="generate_minister_dialogue", exc=e)
            raise

    async def generate_petitions(
        self, participants: list[Minister], game_state: GameState,
    ) -> list[dict]:
        if not participants:
            return []
        prompt_lines = [
            f"当前时间：{game_state.time.year}年{game_state.time.month}月",
            f"国库{game_state.national_treasury}，内帑{game_state.imperial_treasury}，粮草{game_state.grain}",
            "参与朝会大臣：",
        ]
        for p in participants:
            position_text = p.positions[0] if p.positions else "朝臣"
            prompt_lines.append(
                f"- {p.name}（{p.faction}，{position_text}，忠诚{p.loyalty}）"
            )
        prompt_lines.append(
            "请为每位大臣生成一条奏事。只输出JSON，格式："
            '{"petitions":[{"minister_name":"...","content":"...","urgency":"高|中|低"}]}'
        )
        raw_petitions: list = []
        try:
            response = await self._messages_create(
                model=self.model,
                max_tokens=2048,
                system="你是元末至正朝会奏事生成器。仅输出JSON，不要输出额外文本。",
                messages=[{"role": "user", "content": "\n".join(prompt_lines)}],
                temperature=0.6,
            )
            payload = self._load_json_payload(response.content[0].text or "")
            if isinstance(payload, dict):
                raw_petitions = payload.get("petitions", [])
            elif isinstance(payload, list):
                raw_petitions = payload
        except Exception as e:
            log_safe_provider_exception(logger, stage="generate_petitions", exc=e)

        petitions: list[dict] = []
        by_name = {m.name: m for m in participants}
        for item in raw_petitions:
            if not isinstance(item, dict):
                continue
            minister_name = str(item.get("minister_name", "")).strip()
            if minister_name not in by_name:
                continue
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            petitions.append({
                "minister_name": minister_name,
                "content": content,
                "urgency": self._normalize_urgency(str(item.get("urgency", "中"))),
            })

        existing = {p["minister_name"] for p in petitions}
        fallback = await super().generate_petitions(participants, game_state)
        for item in fallback:
            name = str(item.get("minister_name", "")).strip()
            if name and name not in existing:
                petitions.append(item)
        return petitions

    async def generate_debate_speeches(
        self, topic: str, participants: list[Minister], game_state: GameState,
    ) -> list[dict]:
        if not participants:
            return []
        prompt_lines = [
            f"议题：{topic}",
            f"时间：{game_state.time.year}年{game_state.time.month}月",
            "参与朝会大臣：",
        ]
        for p in participants:
            tags = "、".join(p.personality_tags) if p.personality_tags else "无"
            prompt_lines.append(
                f"- {p.name}（{p.faction}，忠诚{p.loyalty}，性格：{tags}）"
            )
        prompt_lines.append(
            "请为每位大臣生成一条发言。仅输出JSON："
            '{"speeches":[{"minister_name":"...","faction":"...","content":"...","stance":"赞成|反对|中立"}]}'
        )
        raw_speeches: list = []
        try:
            response = await self._messages_create(
                model=self.model,
                max_tokens=2048,
                system="你是元末至正朝会辩论生成器。仅输出JSON，不要输出额外文本。",
                messages=[{"role": "user", "content": "\n".join(prompt_lines)}],
                temperature=0.7,
            )
            payload = self._load_json_payload(response.content[0].text or "")
            if isinstance(payload, dict):
                raw_speeches = payload.get("speeches", [])
            elif isinstance(payload, list):
                raw_speeches = payload
        except Exception as e:
            log_safe_provider_exception(logger, stage="generate_debate_speeches", exc=e)

        speeches: list[dict] = []
        by_name = {m.name: m for m in participants}
        for item in raw_speeches:
            if not isinstance(item, dict):
                continue
            minister_name = str(item.get("minister_name", "")).strip()
            minister = by_name.get(minister_name)
            if minister is None:
                continue
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            speeches.append({
                "minister_name": minister_name,
                "faction": str(item.get("faction") or minister.faction),
                "content": content,
                "stance": self._normalize_stance(str(item.get("stance", "中立"))),
            })

        existing = {s["minister_name"] for s in speeches}
        fallback = await super().generate_debate_speeches(topic, participants, game_state)
        for item in fallback:
            name = str(item.get("minister_name", "")).strip()
            if name and name not in existing:
                speeches.append(item)
        return speeches

    async def calculate_vote_tendency(
        self, minister: Minister, decree_type: DecreeType, game_state: GameState,
    ) -> str:
        vote = await super().calculate_vote_tendency(minister, decree_type, game_state)
        if vote == "弃权":
            if minister.loyalty >= 85:
                return "赞成"
            if minister.loyalty <= 20:
                return "反对"
        return vote

    async def generate_assembly_debate(
        self, topic: str, participants: list[Minister], game_state: GameState,
    ) -> dict | None:
        speeches = await self.generate_debate_speeches(topic, participants, game_state)
        if not speeches:
            return template_assembly_debate(topic, participants, game_state)

        speech_map = {
            str(s.get("minister_name")): str(s.get("content", ""))
            for s in speeches if isinstance(s, dict) and s.get("minister_name")
        }
        support_count = sum(1 for s in speeches if isinstance(s, dict) and s.get("stance") == "赞成")
        oppose_count = sum(1 for s in speeches if isinstance(s, dict) and s.get("stance") == "反对")
        if support_count > oppose_count:
            consensus = "support"
        elif oppose_count > support_count:
            consensus = "oppose"
        else:
            consensus = "divided"

        decree_type = infer_decree_type_from_topic(topic) or DecreeType.PERSONNEL
        supporters = [
            str(s.get("minister_name"))
            for s in speeches if isinstance(s, dict) and s.get("stance") == "赞成"
        ]
        return {
            "debate_text": "\n".join(
                f"{s['minister_name']}：{s['content']}" for s in speeches if isinstance(s, dict)
            ),
            "participants": [
                {
                    "name": p.name,
                    "position": p.positions[0] if p.positions else "朝臣",
                    "argument_text": speech_map.get(p.name, ""),
                }
                for p in participants
            ],
            "suggestions": [{
                "title": f"就'{topic}'拟议",
                "description": "请主公据朝议定夺。",
                "decree_type": decree_type.value,
                "supporter_names": supporters[:8],
            }],
            "consensus": consensus,
            "speeches": speeches,
        }

    async def generate_turn_commentary(
        self, summary_data: dict, game_state: GameState,
    ) -> str:
        prompt = build_turn_commentary_prompt(summary_data, game_state)
        try:
            response = await self._messages_create(
                model=self.model,
                max_tokens=1024,
                system=TURN_COMMENTARY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            return response.content[0].text.strip()
        except:
            return "本月无事发生。"

    async def classify_script_choice(
        self,
        player_text: str,
        script_context: dict | None = None,
        *,
        game_state: GameState | None = None,
    ) -> dict:
        choice_count = 0
        if isinstance(script_context, dict) and isinstance(script_context.get("suggested_actions"), list):
            choice_count = len(script_context["suggested_actions"])
        prompt = build_script_choice_classification_prompt(
            player_text,
            script_context,
            game_state=game_state,
        )
        try:
            response = await self._messages_create(
                model=self.model,
                max_tokens=1024,
                system=SCRIPT_CHOICE_CLASSIFICATION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            content = response.content[0].text.strip()
            data = json.loads(extract_json_object_text(content))
            parsed = parse_script_choice_classification_response(
                data,
                choice_count=choice_count,
            )
            if isinstance(parsed, dict):
                return parsed
            return {
                "choice_index": parsed.choice_index,
                "confidence": parsed.confidence,
                "reason": parsed.reason,
            }
        except Exception as e:
            log_safe_provider_exception(logger, stage="classify_script_choice", exc=e)
            return parse_error("脚本选项分类服务暂时不可用", PARSE_ERROR_TYPE_UNAVAILABLE)

    async def select_script_trigger_decisions(
        self,
        game_state: GameState,
        candidates: list[dict],
    ) -> dict[str, tuple[bool, str]] | dict:
        candidate_ids = {
            str(item.get("script_id", "")).strip()
            for item in candidates
            if isinstance(item, dict) and str(item.get("script_id", "")).strip()
        }
        if not candidate_ids:
            return {}

        prompt = build_script_trigger_selection_prompt(game_state, candidates)
        try:
            response = await self._messages_create(
                model=self.model,
                max_tokens=2048,
                system=SCRIPT_TRIGGER_SELECTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            content = response.content[0].text.strip()
            data = json.loads(extract_json_object_text(content))
            parsed = parse_script_trigger_selection_response(
                data,
                candidate_ids=candidate_ids,
            )
            return parsed
        except Exception as e:
            log_safe_provider_exception(
                logger,
                stage="select_script_trigger_decisions",
                exc=e,
            )
            return parse_error("剧情触发决策服务暂时不可用", PARSE_ERROR_TYPE_UNAVAILABLE)

    async def process_freeform(
        self, text: str, game_state: GameState,
        *, script_context: dict | None = None,
    ) -> FreeformResult | dict:
        prompt = _build_freeform_user_prompt(text, game_state, script_context)
        try:
            response = await self._messages_create(
                model=self.model,
                max_tokens=2048,
                system=_FREEFORM_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
            )
            content = response.content[0].text.strip()
            data = json.loads(extract_json_object_text(content))
            return _parse_freeform_response(data, game_state.time.year, game_state.time.month)
        except json.JSONDecodeError as e:
            log_safe_provider_exception(logger, stage="process_freeform_json", exc=e)
            return parse_error("AI返回格式异常", PARSE_ERROR_TYPE_UNAVAILABLE)
        except Exception as e:
            log_safe_provider_exception(logger, stage="process_freeform", exc=e)
            return parse_error("AI服务暂时不可用", PARSE_ERROR_TYPE_UNAVAILABLE)

    async def classify_chat_intent(
        self,
        text: str,
        game_state: GameState,
        conversation_history: list[dict],
    ) -> dict:
        prompt = build_chat_classify_prompt(text, game_state, conversation_history)
        try:
            response = await self._messages_create(
                model=self.model,
                max_tokens=1024,
                system=CHAT_CLASSIFY_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            content = response.content[0].text.strip()
            data = json.loads(extract_json_object_text(content))
            return normalize_chat_intent_payload(data)
        except Exception as e:
            log_safe_provider_exception(logger, stage="classify_chat_intent", exc=e)
            return parse_error("聊天意图分类服务暂时不可用", PARSE_ERROR_TYPE_UNAVAILABLE)

    async def chat_query(
        self,
        text: str,
        game_state: GameState,
        conversation_history: list[dict],
    ) -> str:
        prompt = build_chat_query_prompt(text, game_state, conversation_history)
        try:
            response = await self._messages_create(
                model=self.model,
                max_tokens=1024,
                system=CHAT_QUERY_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
            )
            content = response.content[0].text.strip()
            if not content:
                raise ValueError("chat query reply is empty")
            return content
        except Exception as e:
            log_safe_provider_exception(logger, stage="chat_query", exc=e)
            raise
