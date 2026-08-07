from __future__ import annotations

import base64
import json
import logging
import os
from collections.abc import AsyncIterator

from google import genai
from google.genai import types
from dotenv import load_dotenv

from models.game import GameState, StructuredDecree, Minister, DebateResult, FreeformResult, MinisterReaction, MemorialDraft
from models.enums import DecreeType, MemorialStatus, MinisterStatus
from .fallbacks import template_assembly_debate, template_memorial
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

load_dotenv()


class GoogleProvider(AIProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        prefix: str = "GOOGLE",
    ):
        actual_api_key = api_key or os.getenv(f"{prefix}_API_KEY") or os.getenv("OPENAI_API_KEY")
        actual_base_url = base_url or os.getenv(f"{prefix}_BASE_URL") or os.getenv("OPENAI_BASE_URL", "")

        # google-genai SDK auto-appends /v1beta/models/..., so strip path suffixes
        # e.g. "https://x666.me/v1" -> "https://x666.me"
        for suffix in ("/v1beta", "/v1", "/"):
            if actual_base_url.endswith(suffix):
                actual_base_url = actual_base_url[: -len(suffix)]
                break

        self.client = genai.Client(
            api_key=actual_api_key,
            http_options=types.HttpOptions(base_url=actual_base_url),
        )
        self.model = model or os.getenv(f"{prefix}_MODEL_NAME") or os.getenv(f"{prefix}_MODEL") or os.getenv("OPENAI_MODEL_NAME", "gemini-2.0-flash-exp")
        self._thinking_level = self._load_thinking_level(prefix)

    @staticmethod
    def _normalize_thinking_level(value: object) -> types.ThinkingLevel | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().upper()
        if normalized.startswith("THINKING_LEVEL_"):
            normalized = normalized[len("THINKING_LEVEL_"):]
        mapping = {
            "LOW": types.ThinkingLevel.LOW,
            "MEDIUM": types.ThinkingLevel.MEDIUM,
            "HIGH": types.ThinkingLevel.HIGH,
            "MINIMAL": types.ThinkingLevel.MINIMAL,
            "UNSPECIFIED": types.ThinkingLevel.THINKING_LEVEL_UNSPECIFIED,
        }
        return mapping.get(normalized)

    def _load_thinking_level(self, prefix: str) -> types.ThinkingLevel | None:
        env_name = f"{prefix}_THINKING_CONFIG"
        raw_config = (os.getenv(env_name) or "").strip()
        if not raw_config:
            return None
        try:
            payload = json.loads(raw_config)
        except json.JSONDecodeError as exc:
            logging.warning("Ignore invalid %s JSON: %s", env_name, exc)
            return None
        if not isinstance(payload, dict):
            logging.warning("Ignore non-object %s payload", env_name)
            return None
        raw_level = payload.get("thinkingLevel", payload.get("thinking_level"))
        level = self._normalize_thinking_level(raw_level)
        if raw_level is not None and level is None:
            logging.warning("Ignore unsupported thinkingLevel %r in %s", raw_level, env_name)
        return level

    def _build_generate_content_config(self, **kwargs) -> types.GenerateContentConfig:
        if self._thinking_level is not None:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=self._thinking_level)
        return types.GenerateContentConfig(**kwargs)

    @staticmethod
    def _safety_off() -> list:
        return [
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
        ]

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
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._build_generate_content_config(
                    system_instruction=NARRATIVE_SYSTEM_PROMPT,
                    temperature=0.7,
                    safety_settings=self._safety_off(),
                ),
            )
            return response.text.strip()
        except Exception as e:
            logging.error(f"Google AI generate_narrative error: {e}")
            return "（AI服务响应异常，但政令已执行）"

    async def stream_narrative(
        self, delta_attribution: dict, game_state: GameState,
        chain_events: list[str], decree: StructuredDecree,
    ) -> AsyncIterator[str]:
        prompt = _build_narrative_prompt(delta_attribution, game_state, chain_events, decree)
        config = self._build_generate_content_config(
            system_instruction=NARRATIVE_SYSTEM_PROMPT,
            temperature=0.7,
            safety_settings=self._safety_off(),
        )

        emitted_any = False
        stream_method = getattr(self.client.aio.models, "generate_content_stream", None)
        if callable(stream_method):
            try:
                stream = stream_method(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
                if hasattr(stream, "__await__"):
                    stream = await stream
                if hasattr(stream, "__aiter__"):
                    async for chunk in stream:
                        text = getattr(chunk, "text", None)
                        if isinstance(text, str) and text != "":
                            emitted_any = True
                            yield text
                    return
                for chunk in stream:
                    text = getattr(chunk, "text", None)
                    if isinstance(text, str) and text != "":
                        emitted_any = True
                        yield text
                return
            except Exception as e:
                logging.error(f"Google AI stream_narrative error: {e}")
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
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._build_generate_content_config(
                    system_instruction=PARSE_SYSTEM_PROMPT,
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            content = (response.text or "").strip()
            data = json.loads(extract_json_object_text(content))
            return parse_decree_response(data)

        except json.JSONDecodeError as e:
            logging.error(f"Google AI JSON parse error: {e}")
            return parse_error("AI返回格式异常，请重试")
        except Exception as e:
            logging.error(f"Google AI parse_free_input error: {e}")
            return parse_error(
                "AI解析服务暂时不可用，请使用按钮操作",
                PARSE_ERROR_TYPE_UNAVAILABLE,
            )

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        prompt = f"玩家试图执行以下政令，但被系统拒绝（原有：{reason}）。请以大臣劝谏的口吻，委婉但坚定地告知主公为何不能执行。\n\n政令：{decree}"
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._build_generate_content_config(
                    system_instruction=REJECTION_SYSTEM_PROMPT,
                    temperature=0.7,
                    safety_settings=self._safety_off(),
                ),
            )
            return response.text.strip()
        except Exception:
            return f"主公，此令行不通：{reason}"

    async def generate_debate_narrative(
        self, topic: str, minister_a: Minister, minister_b: Minister, game_state: GameState,
    ) -> DebateResult | None:
        prompt = build_debate_prompt(topic, minister_a, minister_b, game_state)
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=self._build_generate_content_config(
                system_instruction=DEBATE_SYSTEM_PROMPT,
                temperature=0.8,
                response_mime_type="application/json",
            ),
        )
        content = (response.text or "").strip()
        if not content:
            return None
        payload = json.loads(extract_json_object_text(content))
        return parse_debate_response(payload, minister_a, minister_b)



    async def generate_memorial(
        self, trigger_reason: str, author: Minister, game_state: GameState,
    ) -> MemorialDraft:
        prompt = build_memorial_prompt(trigger_reason, author, game_state)
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model, contents=prompt,
                config=self._build_generate_content_config(
                    system_instruction=MEMORIAL_SYSTEM_PROMPT,
                    temperature=0.7,
                    safety_settings=self._safety_off(),
                ),
            )
            draft = parse_memorial_draft(response.text or "", author.name, game_state)
            if not draft.suggested_decrees and trigger_reason.split(":", 1)[0] != "faction_crisis":
                fallback = template_memorial(trigger_reason, author, game_state)
                draft.suggested_decrees = fallback.suggested_decrees
            return draft
        except Exception as e:
            logging.error("GoogleProvider generate_memorial fallback: %s", e)
            return template_memorial(trigger_reason, author, game_state)

    async def generate_minister_reaction(
        self, minister: Minister, decree: StructuredDecree, stance: int, game_state: GameState,
    ) -> str:
        prompt = build_minister_reaction_prompt(minister, decree, stance)
        response = await self.client.aio.models.generate_content(
            model=self.model, contents=prompt,
            config=self._build_generate_content_config(
                system_instruction=MINISTER_REACTION_SYSTEM_PROMPT,
                temperature=0.8,
                safety_settings=self._safety_off(),
            ),
        )
        return response.text.strip()

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
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._build_generate_content_config(
                    system_instruction=MINISTER_DIALOGUE_SYSTEM_PROMPT,
                    temperature=0.6,
                    response_mime_type="application/json",
                    safety_settings=self._safety_off(),
                ),
            )
            content = (response.text or "").strip()
            data = json.loads(extract_json_object_text(content))
            return normalize_dialogue_payload(data)
        except Exception as e:
            logging.error(f"Google generate_minister_dialogue error: {e}")
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
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents="\n".join(prompt_lines),
                config=self._build_generate_content_config(
                    system_instruction="你是元末至正朝会奏事生成器。仅输出JSON，不要输出额外文本。",
                    temperature=0.6,
                    response_mime_type="application/json",
                    safety_settings=self._safety_off(),
                ),
            )
            payload = self._load_json_payload(response.text or "")
            if isinstance(payload, dict):
                raw_petitions = payload.get("petitions", [])
            elif isinstance(payload, list):
                raw_petitions = payload
        except Exception as e:
            logging.error("Google generate_petitions error: %s", e)

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
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents="\n".join(prompt_lines),
                config=self._build_generate_content_config(
                    system_instruction="你是元末至正朝会辩论生成器。仅输出JSON，不要输出额外文本。",
                    temperature=0.7,
                    response_mime_type="application/json",
                    safety_settings=self._safety_off(),
                ),
            )
            payload = self._load_json_payload(response.text or "")
            if isinstance(payload, dict):
                raw_speeches = payload.get("speeches", [])
            elif isinstance(payload, list):
                raw_speeches = payload
        except Exception as e:
            logging.error("Google generate_debate_speeches error: %s", e)

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
        response = await self.client.aio.models.generate_content(
            model=self.model, contents=prompt,
            config=self._build_generate_content_config(
                system_instruction=TURN_COMMENTARY_SYSTEM_PROMPT,
                temperature=0.7,
                safety_settings=self._safety_off(),
            ),
        )
        return response.text.strip()

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
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._build_generate_content_config(
                    system_instruction=SCRIPT_CHOICE_CLASSIFICATION_SYSTEM_PROMPT,
                    temperature=0.1,
                    response_mime_type="application/json",
                    safety_settings=self._safety_off(),
                ),
            )
            content = (response.text or "").strip()
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
            logging.error(f"Google classify_script_choice error: {e}")
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
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._build_generate_content_config(
                    system_instruction=SCRIPT_TRIGGER_SELECTION_SYSTEM_PROMPT,
                    temperature=0.1,
                    response_mime_type="application/json",
                    safety_settings=self._safety_off(),
                ),
            )
            content = (response.text or "").strip()
            data = json.loads(extract_json_object_text(content))
            parsed = parse_script_trigger_selection_response(
                data,
                candidate_ids=candidate_ids,
            )
            return parsed
        except Exception as e:
            logging.error(f"Google select_script_trigger_decisions error: {e}")
            return parse_error("剧情触发决策服务暂时不可用", PARSE_ERROR_TYPE_UNAVAILABLE)

    def _extract_image_b64(self, response) -> str | None:
        images = getattr(response, "generated_images", None)
        if not images:
            return None
        for img in images:
            for candidate in (img, getattr(img, "image", None)):
                if candidate is None:
                    continue
                b64 = getattr(candidate, "bytes_base64_encoded", None) or getattr(candidate, "b64_json", None)
                if isinstance(b64, str) and b64:
                    return f"data:image/png;base64,{b64}"
                raw = getattr(candidate, "image_bytes", None) or getattr(candidate, "bytes", None)
                if isinstance(raw, (bytes, bytearray)) and raw:
                    return f"data:image/png;base64,{base64.b64encode(raw).decode()}"
        return None

    async def process_freeform(
        self, text: str, game_state: GameState,
        *, script_context: dict | None = None,
    ) -> FreeformResult | dict:
        prompt = _build_freeform_user_prompt(text, game_state, script_context)
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._build_generate_content_config(
                    system_instruction=_FREEFORM_SYSTEM_PROMPT,
                    temperature=0.5,
                    response_mime_type="application/json",
                    safety_settings=self._safety_off(),
                ),
            )
            content = (response.text or "").strip()
            data = json.loads(extract_json_object_text(content))
            return _parse_freeform_response(data, game_state.time.year, game_state.time.month)
        except json.JSONDecodeError as e:
            logging.error(f"Google freeform JSON parse error: {e}")
            return parse_error("AI返回格式异常", PARSE_ERROR_TYPE_UNAVAILABLE)
        except Exception as e:
            logging.error(f"Google process_freeform error: {e}")
            return parse_error("AI服务暂时不可用", PARSE_ERROR_TYPE_UNAVAILABLE)

    async def classify_chat_intent(
        self,
        text: str,
        game_state: GameState,
        conversation_history: list[dict],
    ) -> dict:
        prompt = build_chat_classify_prompt(text, game_state, conversation_history)
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._build_generate_content_config(
                    system_instruction=CHAT_CLASSIFY_PROMPT,
                    temperature=0.1,
                    response_mime_type="application/json",
                    safety_settings=self._safety_off(),
                ),
            )
            content = (response.text or "").strip()
            data = json.loads(extract_json_object_text(content))
            return normalize_chat_intent_payload(data)
        except Exception as e:
            logging.error("Google classify_chat_intent error: %s", e)
            return parse_error("聊天意图分类服务暂时不可用", PARSE_ERROR_TYPE_UNAVAILABLE)

    async def chat_query(
        self,
        text: str,
        game_state: GameState,
        conversation_history: list[dict],
    ) -> str:
        prompt = build_chat_query_prompt(text, game_state, conversation_history)
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._build_generate_content_config(
                    system_instruction=CHAT_QUERY_PROMPT,
                    temperature=0.6,
                    safety_settings=self._safety_off(),
                ),
            )
            content = (response.text or "").strip()
            if not content:
                raise ValueError("chat query reply is empty")
            return content
        except Exception as e:
            logging.error("Google chat_query error: %s", e)
            raise
