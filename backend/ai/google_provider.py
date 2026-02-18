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
        self.model = os.getenv("GOOGLE_MODEL_NAME") or os.getenv("OPENAI_MODEL_NAME", "gemini-3-flash-preview")

    @staticmethod
    def _safety_off() -> list:
        return [
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
        ]

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
            f"国库{game_state.treasury}，民心{game_state.civil_morale}，军心{game_state.military_morale}\n\n"
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

    async def generate_assembly_debate(
        self, topic: str, participants: list[Minister], game_state: GameState,
    ) -> dict | None:
        parts = [f"议题：{topic}\n当前国情：{game_state.time.year}年{game_state.time.month}月，"
                 f"国库{game_state.treasury}，民心{game_state.civil_morale}，军心{game_state.military_morale}\n\n参与大臣："]
        for p in participants:
            parts.append(f"- {p.name}（{p.faction}），性格：{'、'.join(p.personality_tags)}，"
                         f"文治{p.abilities.civil}/武略{p.abilities.military}")
        prompt = "\n".join(parts)
        response = await self.client.aio.models.generate_content(
            model=self.model, contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "你是崇祯模拟器的朝会辩论生成器。输出JSON：{"
                    "\"debate_text\":\"300-500字多人对话\","
                    "\"participants\":[{\"name\":\"...\",\"position\":\"...\",\"argument_text\":\"...\"}],"
                    "\"suggestions\":[{\"title\":\"...\",\"description\":\"...\",\"decree_type\":\"...\",\"supporter_names\":[]}],"
                    "\"consensus\":\"共识描述\"}"
                ),
                temperature=0.8,
                response_mime_type="application/json",
            ),
        )
        content = (response.text or "").strip()
        if not content:
            return None
        return json.loads(extract_json_object_text(content))

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
            f"国库{game_state.treasury}，民心{game_state.civil_morale}，军心{game_state.military_morale}，威望{game_state.court_prestige}\n\n"
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
