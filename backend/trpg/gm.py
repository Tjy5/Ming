"""AI 主持人（GM）：基于检定结果生成叙事与分支选项。

- 复用 `backend/ai/` 现有管线（provider.chat_query + 回退约定）。
- 输出结构化 JSON：{narrative, options[3-4], state_changes}。
- AI 不可用 / 输出解析失败 → 规则模板回退。
- **确定性要求**：规则回退必须确定性——同输入同输出，选项带稳定
  option_id（供阶段D脚本化 e2e 通关模拟选择）。
"""
from __future__ import annotations

import json
import logging

from ai.parsers import extract_json_object_text
from models.game import GameState
from models.trpg import (
    TIER_LABELS,
    CharacterSheet,
    RollResult,
)

logger = logging.getLogger(__name__)

# 滚动窗口：最近叙事摘要条数
RECENT_NARRATIVE_WINDOW = 3

MIN_OPTIONS = 3
MAX_OPTIONS = 4

# ── GM 提示词模板 ────────────────────────────────────────

GM_SYSTEM_PROMPT = (
    "你是一款元末明初跑团游戏的主持人（GM），主持朱元璋从布衣到崛起的人生篇章。"
    "请根据玩家行动与检定结果推进剧情，文风凝练、有史意。"
    "只输出一个 JSON 对象，不要输出其他内容。"
)

GM_JSON_SCHEMA = (
    '{"narrative": "叙事文本", '
    '"options": [{"option_id": "稳定英文ID", "label": "选项简述", "description": "选项说明"}], '
    '"state_changes": {}}'
)


def build_gm_prompt(context: dict) -> str:
    """组装 GM 提示词（输入见 generate_turn 的 context 结构）。"""
    roll: RollResult = context["roll"]
    tier_label = TIER_LABELS.get(roll.tier, roll.tier)
    lines = [
        GM_SYSTEM_PROMPT,
        f"当前篇章：《{context['chapter_title']}》，时间：{context['year']}年{context['month']}月。",
        f"主角：{context['player']}，属性摘要：{_attrs_summary(context['attrs'])}。",
        f"玩家行动：{context['action_text']}",
        (
            f"检定结果：掷骰 {roll.roll}，目标值 {roll.target}"
            f"（难度修正 {roll.dc:+d}），结果为【{tier_label}】。"
        ),
    ]
    recent = context.get("recent_narratives") or []
    if recent:
        lines.append("最近剧情摘要：" + "；".join(recent))
    lines.append(
        f"请生成一段叙事和 {MIN_OPTIONS}-{MAX_OPTIONS} 个分支选项，"
        f"严格按如下 JSON 结构输出：{GM_JSON_SCHEMA}"
    )
    return "\n".join(lines)


def _attrs_summary(attrs: dict[str, int]) -> str:
    return "、".join(f"{name}{value}" for name, value in attrs.items())


# ── 规则回退（确定性）───────────────────────────────────

_TIER_NARRATIVES: dict[str, str] = {
    "critical_success": (
        "{year}年，篇章《{chapter_title}》之中，{player}决意{action}。"
        "此举竟得天时地利人和俱全，一蹴而就，声望大涨，左右皆惊以为天命所归。"
    ),
    "success": (
        "{year}年，篇章《{chapter_title}》之中，{player}决意{action}。"
        "一番经营之后，此事顺利办成，根基又固一分。"
    ),
    "failure": (
        "{year}年，篇章《{chapter_title}》之中，{player}决意{action}。"
        "奈何时运不济、事与愿违，此次行动受挫，只得暂且收手，另谋出路。"
    ),
    "critical_failure": (
        "{year}年，篇章《{chapter_title}》之中，{player}决意{action}。"
        "不料横生枝节，非但无功，反酿祸端，局势骤然恶化，须速谋补救。"
    ),
}

# 固定选项模板：稳定 option_id 供脚本化选择（确定性要求）
_SUCCESS_OPTIONS: list[dict] = [
    {
        "option_id": "opt_press_ahead",
        "label": "乘势而进",
        "description": "把握眼下势头，继续推进既定方针。",
    },
    {
        "option_id": "opt_secure_gains",
        "label": "稳固所得",
        "description": "先消化这次成果，积蓄力量再图后举。",
    },
    {
        "option_id": "opt_observe",
        "label": "静观时变",
        "description": "暂缓动作，打探四方消息，等待更好的时机。",
    },
]

_FAILURE_OPTIONS: list[dict] = [
    {
        "option_id": "opt_retry",
        "label": "重整旗鼓",
        "description": "总结此番教训，择机再试一次。",
    },
    {
        "option_id": "opt_retreat",
        "label": "暂避锋芒",
        "description": "先退一步保全自身，避开眼下不利局面。",
    },
    {
        "option_id": "opt_seek_help",
        "label": "另寻助力",
        "description": "投奔亲友或寻觅贵人相助，另辟蹊径。",
    },
]

_EXTRA_OPTION_CRITICAL_SUCCESS: dict = {
    "option_id": "opt_bold_expand",
    "label": "大胆扩张",
    "description": "借此大胜之势，行更大胆的图谋。",
}

_EXTRA_OPTION_CRITICAL_FAILURE: dict = {
    "option_id": "opt_cut_losses",
    "label": "断尾求生",
    "description": "舍弃部分利益与颜面，只求渡过眼前危机。",
}


def rule_based_narrative(context: dict) -> dict:
    """规则模板生成叙事与固定选项。

    确定性保证：同输入必然同输出；选项带稳定 option_id。
    """
    roll: RollResult = context["roll"]
    template = _TIER_NARRATIVES.get(roll.tier, _TIER_NARRATIVES["failure"])
    narrative = template.format(
        year=context["year"],
        chapter_title=context["chapter_title"],
        player=context["player"],
        action=context["action_text"],
    )
    if roll.tier in ("critical_success", "success"):
        options = [dict(option) for option in _SUCCESS_OPTIONS]
        if roll.tier == "critical_success":
            options.append(dict(_EXTRA_OPTION_CRITICAL_SUCCESS))
    else:
        options = [dict(option) for option in _FAILURE_OPTIONS]
        if roll.tier == "critical_failure":
            options.append(dict(_EXTRA_OPTION_CRITICAL_FAILURE))
    return {
        "narrative": narrative,
        "options": options,
        "state_changes": {},
        "source": "rule",
    }


# ── AI 输出解析 ──────────────────────────────────────────

def parse_gm_response(raw: object) -> dict | None:
    """解析 AI 输出为 {narrative, options, state_changes}；无效返回 None。"""
    if not isinstance(raw, str):
        return None
    text = extract_json_object_text(raw)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    narrative = payload.get("narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        return None

    options_raw = payload.get("options")
    if not isinstance(options_raw, list):
        return None
    if not (MIN_OPTIONS <= len(options_raw) <= MAX_OPTIONS):
        return None
    options: list[dict] = []
    for idx, item in enumerate(options_raw):
        if not isinstance(item, dict):
            return None
        label = str(item.get("label") or "").strip()
        if not label:
            return None
        option_id = str(item.get("option_id") or "").strip() or f"opt_ai_{idx + 1}"
        options.append({
            "option_id": option_id,
            "label": label,
            "description": str(item.get("description") or "").strip(),
        })

    state_changes = payload.get("state_changes")
    if not isinstance(state_changes, dict):
        state_changes = {}

    return {
        "narrative": narrative.strip(),
        "options": options,
        "state_changes": state_changes,
    }


# ── 主入口 ───────────────────────────────────────────────

def build_context(
    *,
    state: GameState,
    sheet: CharacterSheet,
    action_text: str,
    roll: RollResult,
    chapter_title: str,
    recent_narratives: list[str] | None = None,
) -> dict:
    """组装 GM 上下文（规则回退与提示词共用，保证两路输入一致）。"""
    return {
        "player": sheet.name,
        "attrs": dict(sheet.attrs),
        "action_text": action_text.strip(),
        "roll": roll,
        "chapter_title": chapter_title,
        "year": state.time.year,
        "month": state.time.month,
        "recent_narratives": list(recent_narratives or [])[-RECENT_NARRATIVE_WINDOW:],
    }


async def generate_turn(
    provider,
    *,
    state: GameState,
    sheet: CharacterSheet,
    action_text: str,
    roll: RollResult,
    chapter_title: str,
    recent_narratives: list[str] | None = None,
) -> dict:
    """生成一回合叙事与分支选项。

    AI 可用且输出合规 → {"source": "ai", ...}；
    AI 不可用 / 解析失败 → 确定性规则回退 {"source": "rule", ...}。
    """
    context = build_context(
        state=state,
        sheet=sheet,
        action_text=action_text,
        roll=roll,
        chapter_title=chapter_title,
        recent_narratives=recent_narratives,
    )
    if provider is not None:
        try:
            raw = await provider.chat_query(build_gm_prompt(context), state, [])
            parsed = parse_gm_response(raw)
            if parsed is not None:
                parsed["source"] = "ai"
                return parsed
            logger.warning("GM AI output parse failed; falling back to rule narrative")
        except Exception:
            logger.warning("GM AI unavailable; falling back to rule narrative")
    return rule_based_narrative(context)
