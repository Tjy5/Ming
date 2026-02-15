from __future__ import annotations

import json
import logging
import os

import httpx
import openai
from dotenv import load_dotenv

from models.game import GameState, StructuredDecree, Minister, DebateResult
from models.enums import DecreeType, PersonnelAction
from .provider import (
    AIProvider,
    PARSE_ERROR_TYPE_UNAVAILABLE,
    parse_error,
    build_debate_prompt,
    DEBATE_SYSTEM_PROMPT,
    parse_debate_response,
    extract_json_object_text,
)

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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

    async def generate_narrative(
        self, delta_attribution: dict, game_state: GameState,
        chain_events: list[str], decree: StructuredDecree,
    ) -> str:
        prompt = self._build_narrative_prompt(delta_attribution, game_state, chain_events, decree)
        
        try:
            response = await self.client.chat.completions.create(
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

    async def parse_free_input(
        self, text: str, game_state: GameState,
    ) -> list[StructuredDecree] | dict:
        prompt = self._build_parse_prompt(text, game_state)
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
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
            response = await self.client.chat.completions.create(
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
        response = await self.client.chat.completions.create(
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

    def _build_narrative_prompt(self, delta, state, events, decree):
        # ... prompt construction logic ...
        return f"""
        当前时间：{state.time.year}年{state.time.month}月
        
        玩家下达了政令：{decree}
        
        数值变化：
        - 国库：{delta.get('treasury', 0)}
        - 民心：{delta.get('civil_morale', 0)}
        - 军心：{delta.get('military_morale', 0)}
        - 威望：{delta.get('court_prestige', 0)}
        
        触发事件：{', '.join(events) if events else '无'}
        
        请生成一段100字左右的叙事，描述政令执行的过程和直接后果。风格要符合明朝历史背景。
        """

    def _build_parse_prompt(self, text, state):
        return f"""
        用户输入："{text}"
        
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
        2) 输入含“斩杀/诛杀/处斩/镇压/清洗”等，优先映射为 harsh_punishment。
        3) 输入明确是人事任免时，使用 personnel，并给出 sub_action=appoint 或 dismiss。
        4) 只有在输入完全不包含政务意图（闲聊、乱码）时，才返回 error。

        仅在无法识别任何政务意图时，返回：
        {{
            "error": "拒绝理由"
        }}
        """
