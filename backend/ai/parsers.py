from __future__ import annotations

from dataclasses import dataclass
import json
import re

from models.game import (
    DebateMinister,
    DebateResult,
    FreeformResult,
    GameEvent,
    GameState,
    MemorialDraft,
    Minister,
    MinisterReaction,
    StructuredDecree,
    EventChoice,
)
from models.enums import DecreeType, DiplomacyTarget, MinisterStatus as _MS, PersonnelAction

from .base import parse_error


@dataclass(slots=True)
class ChoiceClassification:
    choice_index: int | None
    confidence: float
    reason: str


def _normalize_choice_text(text: str) -> str:
    lowered = (text or "").strip().lower()
    return re.sub(r"\s+", "", lowered)


def _char_ngrams(text: str, n: int = 2) -> set[str]:
    if len(text) < n:
        return {text} if text else set()
    return {text[i : i + n] for i in range(0, len(text) - n + 1)}


def _similarity_score(player_text: str, candidate_text: str) -> float:
    if not player_text or not candidate_text:
        return 0.0
    if player_text == candidate_text:
        return 1.0
    if player_text in candidate_text or candidate_text in player_text:
        return 0.95

    player_chars = set(player_text)
    candidate_chars = set(candidate_text)
    if not player_chars or not candidate_chars:
        return 0.0
    char_overlap = len(player_chars & candidate_chars) / len(player_chars | candidate_chars)

    player_grams = _char_ngrams(player_text, 2)
    candidate_grams = _char_ngrams(candidate_text, 2)
    gram_overlap = 0.0
    if player_grams and candidate_grams:
        gram_overlap = len(player_grams & candidate_grams) / len(player_grams | candidate_grams)

    return max(char_overlap * 0.4 + gram_overlap * 0.6, char_overlap)


def _read_suggested_actions(script_context: dict | None) -> list[tuple[int, str, str]]:
    if not isinstance(script_context, dict):
        return []
    raw_actions = script_context.get("suggested_actions")
    if not isinstance(raw_actions, list):
        return []

    actions: list[tuple[int, str, str]] = []
    for idx, item in enumerate(raw_actions):
        if isinstance(item, str):
            label = item.strip()
            description = ""
        elif isinstance(item, dict):
            label = str(item.get("label", "")).strip()
            description = str(item.get("description", "")).strip()
        else:
            continue
        if not label and not description:
            continue
        actions.append((idx, label, description))
    return actions


async def classify_script_choice(
    player_text: str,
    script_context: dict | None = None,
) -> ChoiceClassification:
    normalized_player = _normalize_choice_text(player_text)
    if not normalized_player:
        return ChoiceClassification(
            choice_index=None,
            confidence=0.0,
            reason="输入为空或仅包含空白字符",
        )

    candidates = _read_suggested_actions(script_context)
    if not candidates:
        return ChoiceClassification(
            choice_index=None,
            confidence=0.0,
            reason="事件缺少可匹配的建议行动",
        )

    best_choice_index: int | None = None
    best_confidence = 0.0
    best_label = ""
    for idx, label, description in candidates:
        label_norm = _normalize_choice_text(label)
        full_norm = _normalize_choice_text(f"{label} {description}")
        score = max(
            _similarity_score(normalized_player, label_norm),
            _similarity_score(normalized_player, full_norm),
        )
        if score > best_confidence:
            best_confidence = score
            best_choice_index = idx
            best_label = label or description

    if best_choice_index is None:
        return ChoiceClassification(
            choice_index=None,
            confidence=0.0,
            reason="未找到有效匹配选项",
        )

    return ChoiceClassification(
        choice_index=best_choice_index,
        confidence=round(best_confidence, 3),
        reason=f"最佳匹配：{best_label}",
    )


SCRIPT_CHOICE_CLASSIFICATION_SYSTEM_PROMPT = """\
你是元末明初模拟器的剧情选项分类器。请将玩家输入映射到给定剧情事件的候选选项索引。

你必须严格输出一个JSON对象，不要输出代码块或额外文字：
{
  "choice_index": number|null,
  "confidence": number,  // 0.0~1.0
  "reason": "简短说明"
}

规则：
1. 仅能选择候选列表中的索引（从0开始）
2. 若无法判断或意图过于模糊，choice_index必须为null，confidence应小于0.7
3. confidence需体现把握度，越匹配越高
"""


def _choice_count_from_context(script_context: dict | None) -> int:
    actions = _read_suggested_actions(script_context)
    return len(actions)


def build_script_choice_classification_prompt(
    player_text: str,
    script_context: dict | None = None,
    game_state: GameState | None = None,
) -> str:
    parts: list[str] = [f"玩家输入：{player_text}"]
    if isinstance(script_context, dict):
        parts.append(f"事件标题：{script_context.get('title', '')}")
        parts.append(f"事件描述：{script_context.get('description', '')}")
        actions = _read_suggested_actions(script_context)
        if actions:
            parts.append("候选选项（索引从0开始）：")
            for idx, label, description in actions:
                parts.append(f"{idx}. {label} ｜ {description}")
    if game_state is not None:
        parts.append("\n当前局势摘要：")
        parts.append(_serialize_game_state(game_state))
    return "\n".join(parts)


def parse_script_choice_classification_response(
    data: dict,
    *,
    choice_count: int,
) -> ChoiceClassification | dict:
    if "error" in data:
        return parse_error(str(data["error"]))

    raw_index = data.get("choice_index")
    choice_index: int | None = None
    if raw_index is None:
        choice_index = None
    elif isinstance(raw_index, bool):
        choice_index = None
    else:
        try:
            parsed_index = int(raw_index)
            if 0 <= parsed_index < choice_count:
                choice_index = parsed_index
        except (TypeError, ValueError):
            choice_index = None

    raw_confidence = data.get("confidence", 0.0)
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    reason = str(data.get("reason", "")).strip()
    if not reason:
        reason = "AI未提供理由"

    return ChoiceClassification(
        choice_index=choice_index,
        confidence=confidence,
        reason=reason,
    )


SCRIPT_TRIGGER_SELECTION_SYSTEM_PROMPT = """\
你是元末明初模拟器的剧情触发决策器。请判断候选剧情事件在当前局势下是否应触发。

你必须严格输出一个JSON对象，不要输出代码块或额外文字：
{
  "decisions": [
    {"script_id":"...", "should_trigger": true, "reason":"..."}
  ]
}

规则：
1. 仅能对输入中提供的script_id作决策
2. should_trigger=true 表示本月应触发；false 表示不触发/顺延
3. reason简洁说明依据（如人物已亡、条件不再相关、冲突顺延）
"""


def build_script_trigger_selection_prompt(
    game_state: GameState,
    candidates: list[dict],
) -> str:
    parts: list[str] = [
        "当前局势：",
        _serialize_game_state(game_state),
        "",
        "候选剧情事件：",
    ]
    for item in candidates:
        script_id = str(item.get("script_id", "")).strip()
        title = str(item.get("title", "")).strip()
        description = str(item.get("description", "")).strip()
        is_blocking = bool(item.get("is_blocking", False))
        actions = item.get("suggested_actions", [])
        action_text = ""
        if isinstance(actions, list) and actions:
            rendered = []
            for action in actions:
                if isinstance(action, dict):
                    label = str(action.get("label", "")).strip()
                    desc = str(action.get("description", "")).strip()
                    rendered.append(f"{label}({desc})" if desc else label)
                elif isinstance(action, str):
                    rendered.append(action.strip())
            action_text = "；".join(filter(None, rendered))
        parts.append(
            f"- script_id={script_id}\n"
            f"  标题={title}\n"
            f"  是否阻断={is_blocking}\n"
            f"  描述={description}\n"
            f"  可选方向={action_text}"
        )
    return "\n".join(parts)


def parse_script_trigger_selection_response(
    data: dict,
    *,
    candidate_ids: set[str],
) -> dict[str, tuple[bool, str]] | dict:
    if "error" in data:
        return parse_error(str(data["error"]))

    raw = data.get("decisions")
    if not isinstance(raw, list):
        return parse_error("AI未返回decisions列表")

    decisions: dict[str, tuple[bool, str]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        script_id = str(item.get("script_id", "")).strip()
        if not script_id or script_id not in candidate_ids:
            continue
        should_trigger = bool(item.get("should_trigger", True))
        reason = str(item.get("reason", "")).strip() or "AI未给出理由"
        decisions[script_id] = (should_trigger, reason)

    for script_id in candidate_ids:
        decisions.setdefault(script_id, (True, "AI未返回该事件决策，默认触发"))

    return decisions


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
    "你是元末明初模拟器的朝堂辩论生成器。仅输出一个JSON对象，不要输出Markdown代码块或额外文字。"
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
你是元末明初模拟器的AI执政引擎。玩家扮演元末群雄之主朱元璋（自濠州红巾军亲兵至应天吴王，1368 建明），你负责将玩家的自由文本指令转化为游戏状态变化。

你必须严格输出一个JSON对象，不要输出代码块或额外文字。

输出格式：
{
  "effects": {"点分路径": 数值delta或字符串设值, ...},
  "narrative": "150-300字古风叙事",
  "reactions": [{"minister_name":"大臣名","faction":"派系","reaction_type":"support/oppose/neutral","reaction_text":"反应文本","loyalty_change":0}, ...],
  "rationale": "简要决策说明",
  "new_events": [{"name":"事件名","description":"描述","urgency":"高/中/低","triggered_year":当前年份,"choices":[{"label":"选项","description":"说明","decrees":[],"state_effects":{}}],"historical_basis":"史实依据"}, ...]
}

特殊任务指令（可选）：若玩家指令涉及派遣大臣执行任务，可在effects中添加：
"_mission_<大臣姓名>": {"name":"任务名","total_months":月数(2-12),"cost":花费(≥0),"effects":{"可修改字段路径":数值}}

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
6. new_events单回合最多3个，name必填，urgency默认"中"，triggered_year必须≥当前年份，historical_basis必填
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


def parse_freeform_response(data: dict, current_year: int = 1627, current_month: int = 1) -> FreeformResult | dict:
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
        if k.startswith("_mission_"):
            if not isinstance(v, dict):
                return parse_error("_mission_值必须为dict")
            continue
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

    new_events_raw = data.get("new_events") if isinstance(data.get("new_events"), list) else []
    new_events: list[GameEvent] = []
    from models.enums import EventUrgency
    for evt in new_events_raw:
        if not isinstance(evt, dict):
            continue
        name = evt.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        urgency_raw = evt.get("urgency", "中")
        if urgency_raw not in ("高", "中", "低"):
            urgency_raw = "中"
        triggered_year = evt.get("triggered_year")
        if not isinstance(triggered_year, int):
            triggered_year = None
        triggered_month = evt.get("triggered_month")
        if not isinstance(triggered_month, int) or not (1 <= triggered_month <= 12):
            triggered_month = None
        choices_raw = evt.get("choices") if isinstance(evt.get("choices"), list) else []
        choices = []
        for c in choices_raw:
            try:
                choices.append(EventChoice.model_validate(c))
            except Exception:
                pass
        new_events.append(GameEvent(
            name=name.strip(),
            description=str(evt.get("description", "")),
            urgency=EventUrgency(urgency_raw),
            triggered_year=triggered_year if triggered_year is not None else current_year,
            triggered_month=triggered_month if triggered_month is not None else current_month,
            historical_basis=str(evt.get("historical_basis", "")),
            choices=choices,
        ))

    return FreeformResult(
        effects=effects,
        narrative=narrative,
        reactions=reactions,
        rationale=rationale,
        new_events=new_events,
    )
