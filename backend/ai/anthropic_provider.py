from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from models.game import GameState, StructuredDecree, Minister, DebateResult, FreeformResult, MinisterReaction, MemorialDraft
from models.enums import DecreeType, MemorialStatus, MinisterStatus
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
    infer_decree_type_from_topic,
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


class AnthropicProvider(AIProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        prefix: str = "ANTHROPIC",
    ):
        actual_api_key = api_key or os.getenv(f"{prefix}_API_KEY") or os.getenv("OPENAI_API_KEY")
        actual_base_url = base_url or os.getenv(f"{prefix}_BASE_URL") or os.getenv("OPENAI_BASE_URL", "")

        kwargs = {}
        if actual_api_key:
            kwargs["api_key"] = actual_api_key
        if actual_base_url:
            kwargs["base_url"] = actual_base_url

        self.client = AsyncAnthropic(**kwargs)
        self.model = model or os.getenv(f"{prefix}_MODEL_NAME") or os.getenv(f"{prefix}_MODEL") or "claude-3-5-sonnet-latest"


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
    ) -> str:
        prompt = _build_narrative_prompt(delta_attribution, game_state, chain_events, decree)

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=NARRATIVE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            return response.content[0].text.strip()
        except Exception as e:
            logging.error(f"Anthropic AI generate_narrative error: {e}")
            return "（AI服务响应异常，但政令已执行）"

    async def stream_narrative(
        self, delta_attribution: dict, game_state: GameState,
        chain_events: list[str], decree: StructuredDecree,
    ) -> AsyncIterator[str]:
        prompt = _build_narrative_prompt(delta_attribution, game_state, chain_events, decree)
        
        try:
            async with self.client.messages.stream(
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
            logging.error(f"Anthropic AI stream_narrative error: {e}")
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
            response = await self.client.messages.create(
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
            logging.error(f"Anthropic JSON parse error: {e}")
            return parse_error("AI返回格式异常，请重试")
        except Exception as e:
            logging.error(f"Anthropic parse_free_input error: {e}")
            return parse_error(
                "AI解析服务暂时不可用，请使用按钮操作",
                PARSE_ERROR_TYPE_UNAVAILABLE,
            )

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        prompt = f"玩家试图执行以下政令，但被系统拒绝（原有：{reason}）。请以大臣劝谏的口吻，委婉但坚定地告知陛下为何不能执行。\n\n政令：{decree}"
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=REJECTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            return response.content[0].text.strip()
        except Exception:
            return f"陛下，此令行不通：{reason}"

    async def generate_debate_narrative(
        self, topic: str, minister_a: Minister, minister_b: Minister, game_state: GameState,
    ) -> DebateResult | None:
        prompt = build_debate_prompt(topic, minister_a, minister_b, game_state)
        try:
            response = await self.client.messages.create(
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
            logging.error(f"Anthropic debate error: {e}")
            return None



    async def generate_memorial(
        self, trigger_reason: str, author: Minister, game_state: GameState,
    ) -> MemorialDraft:
        prompt = build_memorial_prompt(trigger_reason, author, game_state)
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=MEMORIAL_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            draft = parse_memorial_draft(response.content[0].text or "", author.name, game_state)
            if not draft.suggested_decrees and trigger_reason.split(":", 1)[0] != "faction_crisis":
                mock = await MockProvider().generate_memorial(trigger_reason, author, game_state)
                draft.suggested_decrees = mock.suggested_decrees
            return draft
        except Exception as e:
            logging.error("AnthropicProvider generate_memorial fallback: %s", e)
            return await MockProvider().generate_memorial(trigger_reason, author, game_state)

    async def generate_minister_reaction(
        self, minister: Minister, decree: StructuredDecree, stance: int, game_state: GameState,
    ) -> str:
        prompt = build_minister_reaction_prompt(minister, decree, stance)
        try:
            response = await self.client.messages.create(
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
            response = await self.client.messages.create(
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
            logging.error(f"Anthropic generate_minister_dialogue error: {e}")
            fallback = await MockProvider().generate_minister_dialogue(
                minister, message, game_state, conversation_history
            )
            return normalize_dialogue_fallback_payload(fallback, minister)

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
            prompt_lines.append(
                f"- {p.name}（{p.faction}，{p.position or '朝臣'}，忠诚{p.loyalty}）"
            )
        prompt_lines.append(
            "请为每位大臣生成一条奏事。只输出JSON，格式："
            '{"petitions":[{"minister_name":"...","content":"...","urgency":"高|中|低"}]}'
        )
        raw_petitions: list = []
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system="你是崇祯朝会奏事生成器。仅输出JSON，不要输出额外文本。",
                messages=[{"role": "user", "content": "\n".join(prompt_lines)}],
                temperature=0.6,
            )
            payload = self._load_json_payload(response.content[0].text or "")
            if isinstance(payload, dict):
                raw_petitions = payload.get("petitions", [])
            elif isinstance(payload, list):
                raw_petitions = payload
        except Exception as e:
            logging.error("Anthropic generate_petitions error: %s", e)

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
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system="你是崇祯朝会辩论生成器。仅输出JSON，不要输出额外文本。",
                messages=[{"role": "user", "content": "\n".join(prompt_lines)}],
                temperature=0.7,
            )
            payload = self._load_json_payload(response.content[0].text or "")
            if isinstance(payload, dict):
                raw_speeches = payload.get("speeches", [])
            elif isinstance(payload, list):
                raw_speeches = payload
        except Exception as e:
            logging.error("Anthropic generate_debate_speeches error: %s", e)

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
            return await MockProvider().generate_assembly_debate(topic, participants, game_state)

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
                {"name": p.name, "position": p.position or "朝臣", "argument_text": speech_map.get(p.name, "")}
                for p in participants
            ],
            "suggestions": [{
                "title": f"就'{topic}'拟议",
                "description": "请陛下据朝议定夺。",
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
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=TURN_COMMENTARY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            return response.content[0].text.strip()
        except:
            return "本月无事发生。"

    async def process_freeform(
        self, text: str, game_state: GameState,
        *, script_context: dict | None = None,
    ) -> FreeformResult | dict:
        prompt = _build_freeform_user_prompt(text, game_state, script_context)
        try:
            response = await self.client.messages.create(
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
            logging.error(f"Anthropic freeform JSON parse error: {e}")
            return parse_error("AI返回格式异常", PARSE_ERROR_TYPE_UNAVAILABLE)
        except Exception as e:
            logging.error(f"Anthropic process_freeform error: {e}")
            return parse_error("AI服务暂时不可用", PARSE_ERROR_TYPE_UNAVAILABLE)
