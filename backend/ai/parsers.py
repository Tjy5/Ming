from __future__ import annotations

import json
import re

from models.game import (
    DebateMinister,
    DebateResult,
    FreeformResult,
    GameState,
    MemorialDraft,
    Minister,
    MinisterReaction,
    StructuredDecree,
)
from models.enums import DecreeType, DiplomacyTarget, MinisterStatus as _MS, PersonnelAction

from .base import parse_error


def build_debate_prompt(
    topic: str,
    minister_a: Minister,
    minister_b: Minister,
    game_state: GameState,
) -> str:
    def _tags(m: Minister) -> str:
        return "、".join(m.personality_tags) if m.personality_tags else "无"

    return (
        f"辩论议题：{topic}\n\n"
        f"大臣甲：{minister_a.name}（{minister_a.faction}），"
        f"性格：{_tags(minister_a)}，"
        f"文治{minister_a.abilities.civil}/武略{minister_a.abilities.military}/外交{minister_a.abilities.diplomacy}\n\n"
        f"大臣乙：{minister_b.name}（{minister_b.faction}），"
        f"性格：{_tags(minister_b)}，"
        f"文治{minister_b.abilities.civil}/武略{minister_b.abilities.military}/外交{minister_b.abilities.diplomacy}\n\n"
        f"当前国情：{game_state.time.year}年{game_state.time.month}月，"
        f"国库{game_state.national_treasury}，民心{game_state.civil_morale}，"
        f"军心{game_state.military_morale}，威望{game_state.court_prestige}\n\n"
        "请严格输出JSON，不要输出额外说明文字。"
    )


DEBATE_SYSTEM_PROMPT = (
    "你是崇祯模拟器的朝堂辩论生成器。仅输出一个JSON对象，不要输出Markdown代码块或额外文字。"
    "字段：debate_text（200-300字），minister_a_position（≤50字），minister_b_position（≤50字），"
    "option_a（{type,target,sub_action}），option_b（同），keywords（字符串数组，≤5个，去重）。"
    "type只能是：tax_increase,tax_decrease,recruit_troops,disband_troops,personnel,diplomacy,disaster_relief,harsh_punishment。"
    "sub_action仅在type=personnel时可用，且只能是appoint或dismiss；其它类型必须为null或省略。"
)


def parse_debate_response(
    data: dict,
    minister_a: Minister,
    minister_b: Minister,
) -> DebateResult | None:
    option_a = _parse_decree_option(data.get("option_a"))
    option_b = _parse_decree_option(data.get("option_b"))
    if option_a is None or option_b is None:
        return None

    debate_text = str(data.get("debate_text", "")).strip()
    if not debate_text:
        return None

    seen: set[str] = set()
    keywords: list[str] = []
    for item in (data.get("keywords") if isinstance(data.get("keywords"), list) else []):
        if not isinstance(item, str):
            continue
        kw = item.strip()
        if kw and kw not in seen:
            seen.add(kw)
            keywords.append(kw)
            if len(keywords) >= 5:
                break

    return DebateResult(
        debate_text=debate_text,
        minister_a=DebateMinister(
            name=minister_a.name,
            faction=minister_a.faction,
            position_summary=str(data.get("minister_a_position", "")).strip()[:50],
        ),
        minister_b=DebateMinister(
            name=minister_b.name,
            faction=minister_b.faction,
            position_summary=str(data.get("minister_b_position", "")).strip()[:50],
        ),
        option_a=option_a,
        option_b=option_b,
        keywords=keywords,
    )


def extract_json_object_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return text

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE).strip()

    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    for idx in range(start, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return text


def _coerce_decree_type(payload: dict) -> DecreeType | None:
    raw_type = payload.get("type")
    if isinstance(raw_type, DecreeType):
        return raw_type
    if isinstance(raw_type, str):
        try:
            return DecreeType(raw_type.strip())
        except ValueError:
            pass

    parts = []
    for key in ("type", "target", "sub_action"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip().lower())
    blob = " ".join(parts)
    if not blob:
        return None

    if re.search(r"tax|税|赋|levy|taxation", blob):
        if re.search(r"increase|raise|add|加|增|higher|heavy", blob):
            return DecreeType.TAX_INCREASE
        if re.search(r"decrease|reduce|cut|免|减|降|lower", blob):
            return DecreeType.TAX_DECREASE
    if re.search(r"agricultur|farm|farming|民生|休养|减负|薄赋", blob):
        return DecreeType.TAX_DECREASE

    if re.search(r"recruit|conscript|enlist|raise.*troop|征兵|募兵|招兵|增兵", blob):
        return DecreeType.RECRUIT_TROOPS
    if re.search(r"disband|demobil|reduce.*troop|裁兵|裁军|遣散", blob):
        return DecreeType.DISBAND_TROOPS

    if re.search(r"diplom|foreign|envoy|alliance|peace|外交|出使|遣使|议和", blob):
        return DecreeType.DIPLOMACY
    if re.search(r"disaster|relief|famine|flood|赈灾|赈济|救灾", blob):
        return DecreeType.DISASTER_RELIEF
    if re.search(r"harsh|punish|strict.*law|刑|峻法|重典|酷刑", blob):
        return DecreeType.HARSH_PUNISHMENT
    if re.search(r"personnel|appoint|dismiss|人事|任命|罢免|撤职|调任", blob):
        return DecreeType.PERSONNEL

    return None


def _coerce_personnel_action(payload: dict) -> PersonnelAction | None:
    raw = payload.get("sub_action")
    if isinstance(raw, PersonnelAction):
        return raw
    if isinstance(raw, str):
        try:
            return PersonnelAction(raw.strip())
        except ValueError:
            pass

    parts = []
    for key in ("type", "target", "sub_action"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip().lower())
    blob = " ".join(parts)
    if re.search(r"dismiss|remove|fire|罢免|撤职|免职|贬", blob):
        return PersonnelAction.DISMISS
    if re.search(r"appoint|promote|assign|任命|擢升|提拔", blob):
        return PersonnelAction.APPOINT
    if re.search(r"execute|kill|slay|behead|斩|诛|处死|赐死|杀", blob):
        return PersonnelAction.EXECUTE
    return None


def _parse_decree_option(payload) -> StructuredDecree | None:
    if not isinstance(payload, dict):
        return None
    try:
        d = dict(payload)
        decree_type = _coerce_decree_type(d)
        if decree_type is None:
            return None

        target = d.get("target")
        if isinstance(target, str):
            target = target.strip() or None
        else:
            target = None

        sub_action = None
        if decree_type == DecreeType.PERSONNEL:
            sub_action = _coerce_personnel_action(d)

        params = d.get("parameters")
        if not isinstance(params, dict):
            params = None

        return StructuredDecree(
            type=decree_type,
            target=target,
            sub_action=sub_action,
            parameters=params,
        )
    except Exception:
        return None


_VALID_DECREE_TYPES = {t.value for t in DecreeType}


def _validate_decrees(decrees: list[StructuredDecree]) -> list[StructuredDecree] | dict:
    validated = []
    for d in decrees:
        if d.type.value not in _VALID_DECREE_TYPES:
            return parse_error("无法识别为有效政令")
        validated.append(d)
    if not validated:
        return parse_error("无法识别为有效政令")
    return validated


def parse_decree_response(data: dict) -> list[StructuredDecree] | dict:
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

    return _validate_decrees(decrees)


def _normalize_decree_type(raw: str) -> str:
    return raw.strip().lower().replace(" ", "_")


def validate_memorial_decrees(
    decrees: list[dict],
    state: GameState,
) -> list[StructuredDecree]:
    region_names = {r.name for r in state.regions}
    minister_names = {m.name for m in state.ministers}
    diplomacy_values = {t.value for t in DiplomacyTarget}

    result: list[StructuredDecree] = []
    for d in decrees:
        if not isinstance(d, dict):
            continue
        raw_type = d.get("type", "")
        if not isinstance(raw_type, str):
            continue
        normalized = _normalize_decree_type(raw_type)
        try:
            dtype = DecreeType(normalized)
        except ValueError:
            continue
        target = d.get("target")
        if isinstance(target, str):
            target = target.strip() or None
        else:
            target = None
        if dtype == DecreeType.DISASTER_RELIEF and (not target or target not in region_names):
            continue
        if dtype == DecreeType.PERSONNEL and (not target or target not in minister_names):
            continue
        if dtype == DecreeType.DIPLOMACY and (not target or target not in diplomacy_values):
            continue
        result.append(StructuredDecree(type=dtype, target=target))
    return result


def parse_memorial_draft(
    raw_json: str,
    author_name: str,
    game_state: GameState,
) -> MemorialDraft:
    data = json.loads(extract_json_object_text(raw_json))
    content = str(data.get("content", "")).strip()
    raw_decrees = data.get("suggested_decrees", [])
    validated = validate_memorial_decrees(
        raw_decrees if isinstance(raw_decrees, list) else [],
        game_state,
    )
    return MemorialDraft(
        content=content or f"臣{author_name}伏奏…",
        suggested_decrees=validated,
    )


_FREEFORM_SYSTEM_PROMPT = """\
你是崇祯模拟器的AI执政引擎。玩家扮演崇祯皇帝，你负责将玩家的自由文本指令转化为游戏状态变化。

你必须严格输出一个JSON对象，不要输出代码块或额外文字。

输出格式：
{
  "effects": {"点分路径": 数值delta或字符串设值, ...},
  "narrative": "150-300字古风叙事",
  "reactions": [{"minister_name":"大臣名","faction":"派系","reaction_type":"support/oppose/neutral","reaction_text":"反应文本","loyalty_change":0}, ...],
  "rationale": "简要决策说明",
  "new_events": [{"name":"事件名","description":"描述","urgency":"高/中/低"}, ...]
}

可修改字段白名单（effects 中只能使用以下路径）：
- global.national_treasury (int delta, 范围0-200)
- global.population (int delta, 范围0-200)
- global.military_strength (int delta, 范围0-200)
- global.civil_morale (int delta, 范围0-100)
- global.military_morale (int delta, 范围0-100)
- global.court_prestige (int delta, 范围0-100)
- minister.{姓名}.loyalty (int delta, 范围0-100)
- minister.{姓名}.status (str: "active"/"idle"/"removed"，removed不可逆)
- minister.{姓名}.abilities.civil/military/diplomacy (int delta, 范围0-100)
- faction.{派系名}.satisfaction (int delta, 范围0-100)
- faction.{派系名}.rebellion_risk (int delta, 范围0-100)
- faction.{派系名}.influence (int delta, 范围0-100)
- region.{区域名}.stability (int delta, 范围0-100)
- region.{区域名}.civil_morale (int delta, 范围0-100)
- region.{区域名}.rebellion_risk (int delta, 范围0-100)
- region.{区域名}.garrison (int delta, ≥0)
- region.{区域名}.disaster_level (int delta, 范围0-100)
- region.{区域名}.tax_rate (float delta, 范围0.0-1.0)
- region.{区域名}.control (str: "朝廷"/"失控"/"沦陷")
- region.{区域名}.threat (str: "none"/"后金"/"民变"/"土司"/"海盗")

规则：
1. 数值类型(int/float)表示增量delta，字符串类型表示直接设值
2. minister姓名必须精确匹配当前大臣列表
3. 不得创造不存在的大臣/区域/派系
4. 若无法识别政务意图，返回 {"error": "无法识别政务意图"}
5. narrative必须与effects一致——若处决某人，narrative必须描述处决事实
6. new_events单回合最多3个，name必填，urgency默认"中"
7. reactions中引用的大臣必须是当前非removed状态的大臣
"""


def _serialize_game_state(state: GameState) -> str:
    t = state.time
    lines = [f"当前时间：{t.era_name}{t.era_year}年（{t.year}年）{t.month}月"]
    lines.append(
        f"国库={state.national_treasury} 人口={state.population} 军需={state.military_strength} "
        f"民心={state.civil_morale} 军心={state.military_morale} 威望={state.court_prestige}"
    )

    lines.append("\n大臣：")
    for m in state.ministers:
        if m.status == _MS.REMOVED:
            continue
        tags = "、".join(m.personality_tags) if m.personality_tags else "无"
        lines.append(
            f"  {m.name}（{m.faction}，{m.status.value}，忠诚{m.loyalty}，"
            f"文{m.abilities.civil}/武{m.abilities.military}/外{m.abilities.diplomacy}，性格：{tags}）"
        )

    lines.append("\n派系：")
    for f in state.factions:
        lines.append(f"  {f.name}（满意度{f.satisfaction} 影响力{f.influence} 叛乱风险{f.rebellion_risk}）")

    lines.append("\n区域：")
    for r in state.regions:
        lines.append(
            f"  {r.name}（稳定{r.stability} 驻军{r.garrison} 控制={r.control.value if hasattr(r.control, 'value') else r.control} "
            f"威胁={r.threat.value if hasattr(r.threat, 'value') else r.threat} 民心{r.civil_morale} "
            f"叛乱{r.rebellion_risk} 灾害{r.disaster_level} 税率{r.tax_rate}）"
        )

    if state.active_events:
        lines.append("\n活跃事件：")
        for e in state.active_events:
            urg = e.urgency.value if hasattr(e.urgency, "value") else e.urgency
            lines.append(f"  {e.name}（紧急度：{urg}）")

    return "\n".join(lines)


def build_freeform_user_prompt(
    text: str,
    state: GameState,
    script_context: dict | None = None,
) -> str:
    parts = [f"玩家指令：{text}"]
    if script_context:
        parts.append(f"\n当前事件背景：{script_context.get('title', '')}")
        parts.append(script_context.get("description", ""))
        actions = script_context.get("suggested_actions")
        if actions:
            parts.append("参考行动方向：" + "、".join(actions))
    parts.append(f"\n当前游戏状态：\n{_serialize_game_state(state)}")
    return "\n".join(parts)


def parse_freeform_response(data: dict) -> FreeformResult | dict:
    if "error" in data:
        return parse_error(data["error"])

    effects = data.get("effects")
    if effects is None:
        return parse_error("AI未返回effects字段")
    if not isinstance(effects, dict):
        return parse_error("effects格式无效")
    for k, v in effects.items():
        if not isinstance(k, str):
            return parse_error("effects路径格式无效")
        if isinstance(v, (dict, list)):
            return parse_error("effects包含嵌套结构")
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            return parse_error("effects值类型无效")

    narrative = str(data.get("narrative", ""))
    rationale = str(data.get("rationale", ""))

    def _safe_int(raw) -> int:
        if isinstance(raw, bool):
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    reactions = []
    for r in (data.get("reactions") or []):
        if not isinstance(r, dict):
            continue
        name = r.get("minister_name", "")
        if not name:
            continue
        reactions.append(
            MinisterReaction(
                minister_name=str(name),
                faction=str(r.get("faction", "")),
                reaction_type=str(r.get("reaction_type", "neutral")),
                reaction_text=str(r.get("reaction_text", f"{name}：臣遵旨。")),
                loyalty_change=_safe_int(r.get("loyalty_change", 0)),
            )
        )

    new_events = data.get("new_events") if isinstance(data.get("new_events"), list) else []

    return FreeformResult(
        effects=effects,
        narrative=narrative,
        reactions=reactions,
        rationale=rationale,
        new_events=new_events,
    )
