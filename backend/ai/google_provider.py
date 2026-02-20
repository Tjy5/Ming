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
from models.enums import DecreeType, PersonnelAction, MemorialStatus, MinisterStatus
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
    infer_decree_type_from_topic,
)

load_dotenv()


class GoogleProvider(AIProvider):
    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("GOOGLE_BASE_URL") or os.getenv("OPENAI_BASE_URL", "")

        # google-genai SDK auto-appends /v1beta/models/..., so strip path suffixes
        # e.g. "https://x666.me/v1" -> "https://x666.me"
        for suffix in ("/v1beta", "/v1", "/"):
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)]
                break

        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(base_url=base_url),
        )
        self.model = os.getenv("GOOGLE_MODEL_NAME") or os.getenv("OPENAI_MODEL_NAME", "gemini-2.0-flash-exp")

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
    ) -> str:
        prompt = self._build_narrative_prompt(delta_attribution, game_state, chain_events, decree)

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="你是一款历史模拟游戏（崇祯模拟器）的AI引擎。你的任务是根据玩家的政令和游戏状态，生成一段生动、古风的历史叙事，描述政令的执行结果和影响。请注意，为了还原历史真实性，对于战争、灾害等事件的描述可能涉及暴力或死亡，这是游戏背景所必需的，请勿回避。",
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
        prompt = self._build_narrative_prompt(delta_attribution, game_state, chain_events, decree)
        config = types.GenerateContentConfig(
            system_instruction="你是一款历史模拟游戏（崇祯模拟器）的AI引擎。你的任务是根据玩家的政令和游戏状态，生成一段生动、古风的历史叙事，描述政令的执行结果和影响。请注意，为了还原历史真实性，对于战争、灾害等事件的描述可能涉及暴力或死亡，这是游戏背景所必需的，请勿回避。",
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
        prompt = self._build_parse_prompt(text, game_state)

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="你是一款历史模拟游戏的指令解析器。将用户的自然语言输入解析为结构化的政令JSON。",
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            content = (response.text or "").strip()
            data = json.loads(extract_json_object_text(content))

            if "error" in data:
                return parse_error(data["error"])

            decrees = []
            for item in data.get("decrees", []):
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
            logging.error(f"Google AI JSON parse error: {e}")
            return parse_error("AI返回格式异常，请重试")
        except Exception as e:
            logging.error(f"Google AI parse_free_input error: {e}")
            return parse_error(
                "AI解析服务暂时不可用，请使用按钮操作",
                PARSE_ERROR_TYPE_UNAVAILABLE,
            )

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        prompt = f"玩家试图执行以下政令，但被系统拒绝（原有：{reason}）。请以大臣劝谏的口吻，委婉但坚定地告知陛下为何不能执行。\n\n政令：{decree}"
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="你是一名为国分忧的大臣。请解释为何不能执行某项政令。请注意，为了还原历史真实性，对于战争、灾害等事件的描述可能涉及暴力或死亡，这是游戏背景所必需的，请勿回避。",
                    temperature=0.7,
                    safety_settings=self._safety_off(),
                ),
            )
            return response.text.strip()
        except Exception:
            return f"陛下，此令行不通：{reason}"

    async def generate_debate_narrative(
        self, topic: str, minister_a: Minister, minister_b: Minister, game_state: GameState,
    ) -> DebateResult | None:
        prompt = build_debate_prompt(topic, minister_a, minister_b, game_state)
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
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

    async def generate_portrait(self, minister_name: str, description: str) -> str | None:
        generate_images = getattr(getattr(getattr(self.client, "aio", None), "models", None), "generate_images", None)
        if generate_images is None:
            return None
        prompt = (
            "Ming dynasty official portrait, traditional Chinese court painting style. "
            f"Minister: {minister_name}. {description}. "
            "Half-body portrait, formal robe, neutral background."
        )
        model_name = os.getenv("GOOGLE_IMAGE_MODEL_NAME", "imagen-3.0-generate-002")
        config_cls = getattr(types, "GenerateImagesConfig", None)
        kwargs: dict = {"model": model_name, "prompt": prompt}
        if config_cls:
            kwargs["config"] = config_cls(number_of_images=1)
        response = await generate_images(**kwargs)
        return self._extract_image_b64(response)

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
            response = await self.client.aio.models.generate_content(
                model=self.model, contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="你是崇祯模拟器的奏折生成器。以明朝大臣口吻撰写奏折，文风典雅庄重。仅输出JSON。",
                    temperature=0.7,
                    safety_settings=self._safety_off(),
                ),
            )
            draft = parse_memorial_draft(response.text or "", author.name, game_state)
            if not draft.suggested_decrees and trigger_reason.split(":", 1)[0] != "faction_crisis":
                mock = await MockProvider().generate_memorial(trigger_reason, author, game_state)
                draft.suggested_decrees = mock.suggested_decrees
            return draft
        except Exception as e:
            logging.error("GoogleProvider generate_memorial fallback: %s", e)
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
        response = await self.client.aio.models.generate_content(
            model=self.model, contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="你是崇祯模拟器的大臣反应生成器。输出一句简短的大臣反应，30-50字。",
                temperature=0.8,
                safety_settings=self._safety_off(),
            ),
        )
        return response.text.strip()

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
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "你是崇祯朝大臣角色扮演引擎。"
                        "必须以第一人称回复皇帝，语气要符合该大臣身份、派系与性格。"
                        "回复内容要结合当前国情与对话历史。"
                        "仅输出JSON：{\"reply\":\"...\",\"loyalty_change\":0,\"mood\":\"neutral\"}。"
                        "loyalty_change 必须是 -3 到 3 的整数。"
                        "mood 只能是 support、neutral、oppose。"
                    ),
                    temperature=0.6,
                    response_mime_type="application/json",
                    safety_settings=self._safety_off(),
                ),
            )
            content = (response.text or "").strip()
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
            logging.error(f"Google generate_minister_dialogue error: {e}")
            fallback = await MockProvider().generate_minister_dialogue(
                minister, message, game_state, conversation_history
            )
            raw_loyalty_change = fallback.get("loyalty_change", 0)
            try:
                loyalty_change = int(raw_loyalty_change)
            except (TypeError, ValueError):
                loyalty_change = 0
            loyalty_change = max(-3, min(3, loyalty_change))

            raw_mood = str(fallback.get("mood", "neutral")).strip().lower()
            mood_map = {"恭顺": "support", "欣慰": "support", "愤怒": "oppose", "阳奉阴违": "oppose", "惶恐": "neutral"}
            mood = raw_mood if raw_mood in {"support", "neutral", "oppose"} else mood_map.get(raw_mood, "neutral")
            reply = str(fallback.get("reply", "")).strip() or f"臣{minister.name}谨遵圣意。"
            return {"reply": reply, "loyalty_change": loyalty_change, "mood": mood}

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
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents="\n".join(prompt_lines),
                config=types.GenerateContentConfig(
                    system_instruction="你是崇祯朝会奏事生成器。仅输出JSON，不要输出额外文本。",
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
                config=types.GenerateContentConfig(
                    system_instruction="你是崇祯朝会辩论生成器。仅输出JSON，不要输出额外文本。",
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
        response = await self.client.aio.models.generate_content(
            model=self.model, contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="你是崇祯模拟器的朝政总评生成器。输出50-100字的朝政概况。",
                temperature=0.7,
                safety_settings=self._safety_off(),
            ),
        )
        return response.text.strip()

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

    async def process_freeform(
        self, text: str, game_state: GameState,
        *, script_context: dict | None = None,
    ) -> FreeformResult | dict:
        prompt = self._build_freeform_prompt(text, game_state, script_context)
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_FREEFORM_SYSTEM_PROMPT,
                    temperature=0.5,
                    response_mime_type="application/json",
                    safety_settings=self._safety_off(),
                ),
            )
            content = (response.text or "").strip()
            data = json.loads(extract_json_object_text(content))
            return _parse_freeform_response(data)
        except json.JSONDecodeError as e:
            logging.error(f"Google freeform JSON parse error: {e}")
            return parse_error("AI返回格式异常", PARSE_ERROR_TYPE_UNAVAILABLE)
        except Exception as e:
            logging.error(f"Google process_freeform error: {e}")
            return parse_error("AI服务暂时不可用", PARSE_ERROR_TYPE_UNAVAILABLE)

    @staticmethod
    def _build_freeform_prompt(
        text: str, state: GameState, script_context: dict | None = None,
    ) -> str:
        return _build_freeform_user_prompt(text, state, script_context)

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
