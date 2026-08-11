from __future__ import annotations

"""Deterministic fallback logic for AI failure paths.

These functions are used when a *configured* AI provider fails at runtime:
memorials, minister reactions, debate summaries, turn commentary, and the
optional keyword-based freeform decree parsing fallback (gated separately by
AI_RULE_PARSE_FALLBACK).

They are NOT a provider mode — the game requires a configured AI provider
(AI_PROVIDER + API key) to play. This module only keeps the game playable
for a few seconds of degraded output when the real provider errors.
"""

import re

from models.game import (
    FreeformResult,
    GameState,
    MemorialDraft,
    Minister,
    StructuredDecree,
)
from models.enums import DecreeType, PersonnelAction

from .base import (
    PARSE_ERROR_TYPE_UNAVAILABLE,
    infer_decree_type_from_topic,
    parse_error,
)
from .parsers import classify_script_choice as _classify_script_choice

NARRATIVE_TEMPLATES: dict[DecreeType, str] = {
    DecreeType.TAX_INCREASE: "朕下旨加征赋税，国库增银{treasury}万两。然百姓怨声载道，民心{civil_morale}。{chain}",
    DecreeType.TAX_DECREASE: "朕体恤百姓，下旨减免赋税。国库虽减{treasury}，民心却得{civil_morale}之振。{chain}",
    DecreeType.RECRUIT_TROOPS: "朕令各地募兵备战，军备增{military_supply}，然征兵之费耗银{treasury}，百姓亦有离散。{chain}",
    DecreeType.DISBAND_TROOPS: "朕令裁撤冗兵，省银{treasury}万两，然军备减{military_supply}，将士离心。{chain}",
    DecreeType.PERSONNEL: "朕调整朝廷人事，威望{court_prestige}。朝堂格局为之一变。{chain}",
    DecreeType.DIPLOMACY: "朕遣使出使{target}，费银{treasury}万两。军心{military_morale}，朝廷威望{court_prestige}。{chain}",
    DecreeType.DISASTER_RELIEF: "朕拨银赈济{target}，费银{treasury}万两。灾民感恩戴德，民心{civil_morale}。{chain}",
    DecreeType.HARSH_PUNISHMENT: "朕下旨严刑峻法，以正纲纪。然百姓畏惧，民心{civil_morale}。{chain}",
}

REJECTION_TEMPLATES: dict[DecreeType, str] = {
    DecreeType.TAX_INCREASE: "主公，民心已然不稳，再加赋税恐激民变。臣请主公三思。",
    DecreeType.TAX_DECREASE: "主公，国库空虚，实难再减赋税。臣请主公先充实国库。",
    DecreeType.RECRUIT_TROOPS: "主公，钱粮或人口不足，难以征兵。臣请主公筹措资源后再议。",
    DecreeType.DISBAND_TROOPS: "主公，军备不足，裁兵恐致边防空虚。臣请主公慎重。",
    DecreeType.PERSONNEL: "主公，朝廷威望不足以服众，此时人事变动恐生乱象。",
    DecreeType.DIPLOMACY: "主公，国库不足以支撑外交使费。臣请主公先充实国库。",
    DecreeType.DISASTER_RELIEF: "主公，国库仅余有限银两，实难拨付赈灾银两。臣请主公先充实国库，再议赈济之事。",
    DecreeType.HARSH_PUNISHMENT: "主公，朝廷威望不足，严刑峻法恐适得其反。",
}

NEGATION_KEYWORDS = re.compile(r"不要|别|勿|禁止")

KEYWORD_MAP: list[tuple[re.Pattern, DecreeType, dict | None]] = [
    (re.compile(r"加税|加征|增税|征税|加赋"), DecreeType.TAX_INCREASE, None),
    (re.compile(r"减税|免税|降税|减赋"), DecreeType.TAX_DECREASE, None),
    (re.compile(r"招兵|募兵|增兵|征兵"), DecreeType.RECRUIT_TROOPS, None),
    (re.compile(r"裁兵|裁军|遣散|削兵"), DecreeType.DISBAND_TROOPS, None),
    (re.compile(r"任命|提拔|擢升"), DecreeType.PERSONNEL, {"sub_action": PersonnelAction.APPOINT}),
    (re.compile(r"罢免|撤职|贬谪|免职|问罪"), DecreeType.PERSONNEL, {"sub_action": PersonnelAction.DISMISS}),
    (re.compile(r"外交|遣使|出使|议和"), DecreeType.DIPLOMACY, None),
    (re.compile(r"赈灾|赈济|救灾|拨银"), DecreeType.DISASTER_RELIEF, None),
    (re.compile(r"严刑|峻法|严法|重典|酷刑|镇压|清洗"), DecreeType.HARSH_PUNISHMENT, None),
    (re.compile(r"斩首|斩杀|问斩|处斩|诛杀|诛灭"), DecreeType.HARSH_PUNISHMENT, None),
]

_EXEC_VERB = r"斩首|斩杀|问斩|处斩|诛杀|诛灭|斩了|斩掉|杀了|赐死"
EXECUTION_PREFIX_RE = re.compile(rf"(?:{_EXEC_VERB})([^\s,，。、]{{2,4}})")
EXECUTION_SUFFIX_RE = re.compile(rf"(?:把|将)?([^\s,，。、]{{2,4}})(?:{_EXEC_VERB})")

REGION_KEYWORDS = re.compile(r"应天|太平|镇江|两淮|杭州|武昌|平江|大都")
DIPLOMACY_KEYWORDS = re.compile(r"龙凤政权|汉政权|吴政权|元廷|东南群雄|陈友谅|张士诚|方国珍")
PERSON_PATTERN = re.compile(r"(?:把|将|令|命)?([^\s,，。、]{2,4})(?:调|贬|擢|免|罢|任|撤)")
_VACANCY_HINTS = ("空缺", "继任", "补缺", "替补", "vacancy")
EXPLORE_PREFIX = "详细介绍当前局势："


def _try_parse_execution(
    text: str,
    game_state: GameState,
) -> list[StructuredDecree] | None:
    minister_names = {m.name for m in game_state.ministers if m.status.value != "removed"}
    for pat in (EXECUTION_PREFIX_RE, EXECUTION_SUFFIX_RE):
        match = pat.search(text)
        if match:
            candidate = match.group(1)
            if candidate in minister_names:
                return [
                    StructuredDecree(
                        type=DecreeType.PERSONNEL,
                        target=candidate,
                        sub_action=PersonnelAction.EXECUTE,
                    )
                ]
    return None


def _format_delta(val: int) -> str:
    return f"+{val}" if val > 0 else str(val)


def template_narrative(
    delta_attribution: dict,
    game_state: GameState,
    chain_events: list[str],
    decree: StructuredDecree,
) -> str:
    tpl = NARRATIVE_TEMPLATES[decree.type]
    vals = {}
    for key in (
        "treasury",
        "population",
        "military_supply",
        "civil_morale",
        "military_morale",
        "court_prestige",
    ):
        total = 0
        if key in delta_attribution:
            total = sum(delta_attribution[key].values())
        vals[key] = _format_delta(total)
    vals["target"] = decree.target or ""
    vals["chain"] = "".join(f"【{e}】事件爆发！" for e in chain_events) if chain_events else ""
    return tpl.format(**vals)


def rule_parse_free_input(
    text: str,
    game_state: GameState,
) -> list[StructuredDecree] | dict:
    if NEGATION_KEYWORDS.search(text):
        return parse_error("检测到否定指令，请直接描述您想执行的政令")
    exec_result = _try_parse_execution(text, game_state)
    if exec_result:
        return exec_result
    results: list[StructuredDecree] = []
    for pattern, dtype, extra in KEYWORD_MAP:
        if pattern.search(text):
            kwargs: dict = {"type": dtype}
            if extra and "sub_action" in extra:
                kwargs["sub_action"] = extra["sub_action"]
                m = PERSON_PATTERN.search(text)
                if m:
                    kwargs["target"] = m.group(1)
            if dtype == DecreeType.DISASTER_RELIEF:
                m = REGION_KEYWORDS.search(text)
                if m:
                    kwargs["target"] = m.group(0)
            if dtype == DecreeType.DIPLOMACY:
                m = DIPLOMACY_KEYWORDS.search(text)
                if m:
                    kwargs["target"] = m.group(0)
            results.append(StructuredDecree(**kwargs))
    if not results:
        return parse_error("无法识别具体政令，请使用按钮操作或描述具体政令内容")
    return results


def template_rejection(decree: StructuredDecree, reason: str) -> str:
    return REJECTION_TEMPLATES.get(decree.type, f"主公，此令无法执行：{reason}")


def template_memorial(
    trigger_reason: str,
    author: Minister,
    game_state: GameState,
) -> MemorialDraft:
    parts = trigger_reason.split(":", 1)
    trigger_type = parts[0] if parts[0] else ""
    entity = parts[1] if len(parts) > 1 else ""

    decrees: list[StructuredDecree] = []
    if trigger_type == "region_crisis" and entity:
        decrees = [StructuredDecree(type=DecreeType.DISASTER_RELIEF, target=entity)]
    elif trigger_type == "rebellion_warning":
        decrees = [StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)]
    elif trigger_type == "military_crisis":
        decrees = [StructuredDecree(type=DecreeType.RECRUIT_TROOPS)]

    content = f"臣{author.name}伏惟主公钧鉴：{trigger_reason}事关社稷安危，臣不敢不奏。伏乞裁断。"
    return MemorialDraft(content=content, suggested_decrees=decrees)


def template_minister_reaction(
    minister: Minister,
    decree: StructuredDecree,
    stance: int,
    game_state: GameState,
) -> str:
    if stance > 0:
        return f"{minister.name}拱手道：主公圣明。"
    return f"{minister.name}跪奏：臣以为此举不妥，恳请主公三思。"


def rule_vote_tendency(
    minister: Minister,
    decree_type: DecreeType,
    game_state: GameState,
) -> str:
    try:
        from engine.tables import FACTION_STANCE

        faction_stance = int(FACTION_STANCE.get(minister.faction, {}).get(decree_type, 0))
    except Exception:
        faction_stance = 0
    score = faction_stance + (minister.loyalty - 50) / 3
    if score >= 12:
        return "赞成"
    if score <= -12:
        return "反对"
    return "弃权"


def rule_debate_speeches(
    topic: str,
    participants: list[Minister],
    game_state: GameState,
) -> list[dict]:
    decree_type = infer_decree_type_from_topic(topic) or DecreeType.PERSONNEL
    speeches: list[dict] = []
    for minister in participants:
        tendency = rule_vote_tendency(minister, decree_type, game_state)
        stance = "中立"
        if tendency == "赞成":
            stance = "赞成"
        elif tendency == "反对":
            stance = "反对"
        speeches.append(
            {
                "minister_name": minister.name,
                "faction": minister.faction,
                "content": (
                    f"臣{minister.name}以为'{topic}'当"
                    f"{('力行' if stance == '赞成' else '慎行' if stance == '反对' else '缓议')}，请主公裁断。"
                ),
                "stance": stance,
            }
        )
    return speeches


def template_assembly_debate(
    topic: str,
    participants: list[Minister],
    game_state: GameState,
) -> dict:
    speeches = rule_debate_speeches(topic, participants, game_state)
    speech_by_name = {
        str(item.get("minister_name")): str(item.get("content", ""))
        for item in speeches
        if isinstance(item, dict) and item.get("minister_name")
    }
    supporters = [
        str(item.get("minister_name"))
        for item in speeches
        if isinstance(item, dict) and item.get("stance") == "赞成"
    ]
    opposers = [
        str(item.get("minister_name"))
        for item in speeches
        if isinstance(item, dict) and item.get("stance") == "反对"
    ]
    consensus = "divided"
    if len(supporters) > len(opposers):
        consensus = "support"
    elif len(opposers) > len(supporters):
        consensus = "oppose"
    decree_type = infer_decree_type_from_topic(topic) or DecreeType.PERSONNEL
    return {
        "debate_text": "\n".join(
            f"{s['minister_name']}：{s['content']}" for s in speeches if isinstance(s, dict)
        ),
        "participants": [
            {
                "name": p.name,
                "position": p.positions[0] if p.positions else "朝臣",
                "argument_text": speech_by_name.get(p.name, ""),
            }
            for p in participants
        ],
        "suggestions": [
            {
                "title": f"就'{topic}'拟议",
                "description": "请主公依朝议结果酌定施行。",
                "decree_type": decree_type.value,
                "supporter_names": supporters[:8],
            }
        ],
        "consensus": consensus,
        "speeches": speeches,
    }


def rule_petitions(participants: list[Minister]) -> list[dict]:
    petitions: list[dict] = []
    for minister in participants:
        urgency = "中"
        if minister.abilities.military >= 80:
            urgency = "高"
        elif minister.abilities.civil < 40 and minister.loyalty < 40:
            urgency = "低"
        petitions.append(
            {
                "minister_name": minister.name,
                "content": f"臣{minister.name}谨奏：当下{minister.faction}所忧之政务，宜速议定施行。",
                "urgency": urgency,
            }
        )
    return petitions


def template_action_implications(
    summary_data: dict,
    game_state: GameState,
) -> list[str]:
    rule_based = summary_data.get("rule_based_implications", [])
    return [str(x) for x in (rule_based or [])][:3]


def template_turn_commentary(
    summary_data: dict,
    game_state: GameState,
) -> str:
    year = int(summary_data.get("year") or game_state.time.year)
    month = int(summary_data.get("month") or game_state.time.month)
    major_events = summary_data.get("major_events", [])
    action_implications = summary_data.get("action_implications", [])

    count = len(major_events)
    has_action = bool(action_implications)
    if count > 0:
        tone = "动荡"
    elif has_action:
        tone = "有变"
    else:
        tone = "平稳"

    action_text = "；".join(str(x) for x in action_implications[:2]) if has_action else "暂无显著政务变化"
    return f"{year}年{month}月朝政{tone}，{count}件大事需关注。{action_text}。"


async def rule_classify_script_choice(
    player_text: str,
    script_context: dict | None = None,
) -> dict:
    try:
        classified = await _classify_script_choice(player_text, script_context)
    except Exception:
        return parse_error(
            "脚本选项分类失败",
            PARSE_ERROR_TYPE_UNAVAILABLE,
        )
    return {
        "choice_index": classified.choice_index,
        "confidence": classified.confidence,
        "reason": classified.reason,
    }


def _trigger_candidate_text_blob(candidate: dict) -> str:
    parts: list[str] = [
        str(candidate.get("title", "")).strip(),
        str(candidate.get("description", "")).strip(),
    ]
    actions = candidate.get("suggested_actions")
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict):
                parts.append(str(action.get("label", "")).strip())
                parts.append(str(action.get("description", "")).strip())
            elif isinstance(action, str):
                parts.append(action.strip())
    return " ".join(part for part in parts if part).strip()


def _trigger_has_vacancy_fallback(text: str) -> bool:
    lower_text = text.lower()
    return any(hint in text or hint in lower_text for hint in _VACANCY_HINTS)


def _trigger_condition_accepts_removed(
    condition_spec: dict | None,
    removed_names: set[str],
) -> bool:
    if not isinstance(condition_spec, dict) or not removed_names:
        return False
    node_type = condition_spec.get("type")
    if node_type == "minister_removed":
        name = condition_spec.get("name")
        return isinstance(name, str) and name in removed_names
    if node_type == "and":
        children = condition_spec.get("conditions")
        if isinstance(children, list):
            return any(
                _trigger_condition_accepts_removed(child, removed_names)
                for child in children
                if isinstance(child, dict)
            )
    return False


def _trigger_candidate_relevance_score(
    state: GameState,
    candidate: dict,
) -> tuple[int, int, str]:
    score = 0
    if candidate.get("is_blocking"):
        score += 100

    actions = candidate.get("suggested_actions")
    if isinstance(actions, list):
        score += len(actions) * 5

    description = str(candidate.get("description", "")).strip()
    score += min(len(description) // 120, 5)

    active_names = {
        m.name for m in state.ministers
        if m.status.value in {"active", "idle"}
    }
    text = _trigger_candidate_text_blob(candidate)
    score += sum(1 for name in active_names if name and name in text)

    title = str(candidate.get("title", "")).strip()
    script_id = str(candidate.get("script_id", "")).strip()
    return score, len(title), script_id


def rule_script_trigger_decisions(
    game_state: GameState,
    candidates: list[dict],
) -> dict[str, tuple[bool, str]]:
    decisions: dict[str, tuple[bool, str]] = {}
    normalized_candidates: list[dict] = []
    removed_names = {
        m.name for m in game_state.ministers
        if m.status.value == "removed"
    }

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        script_id = str(candidate.get("script_id", "")).strip()
        if not script_id:
            continue
        normalized_candidates.append(candidate)
        text = _trigger_candidate_text_blob(candidate)
        mentioned_removed = [name for name in removed_names if name and name in text]
        if (
            mentioned_removed
            and not _trigger_has_vacancy_fallback(text)
            and not _trigger_condition_accepts_removed(
                candidate.get("condition"),
                set(mentioned_removed),
            )
        ):
            decisions[script_id] = (
                False,
                f"关键人物已不在朝：{'、'.join(sorted(mentioned_removed))}",
            )
        else:
            decisions[script_id] = (True, "规则通过且与当前局势相关")

    triggerable_blocking = [
        candidate for candidate in normalized_candidates
        if bool(candidate.get("is_blocking"))
        and decisions.get(str(candidate.get("script_id", "")).strip(), (False, ""))[0]
    ]
    if len(triggerable_blocking) > 1:
        selected = max(
            triggerable_blocking,
            key=lambda item: _trigger_candidate_relevance_score(game_state, item),
        )
        selected_id = str(selected.get("script_id", "")).strip()
        selected_title = str(selected.get("title", "")).strip()
        for candidate in triggerable_blocking:
            script_id = str(candidate.get("script_id", "")).strip()
            if script_id == selected_id:
                continue
            decisions[script_id] = (
                False,
                f"与同月更紧急事件冲突，顺延处理：{selected_title}",
            )

    for candidate in normalized_candidates:
        script_id = str(candidate.get("script_id", "")).strip()
        if script_id:
            decisions.setdefault(script_id, (True, "规则触发"))
    return decisions


def rule_process_freeform(
    text: str,
    game_state: GameState,
) -> FreeformResult | dict:
    minister_names = {m.name for m in game_state.ministers if m.status.value != "removed"}

    for pat in (EXECUTION_PREFIX_RE, EXECUTION_SUFFIX_RE):
        match = pat.search(text)
        if match and match.group(1) in minister_names:
            name = match.group(1)
            return FreeformResult(
                effects={f"minister.{name}.status": "removed"},
                narrative=f"主公勃然大怒，下令将{name}押赴刑场，斩首示众。",
                rationale=f"处决{name}",
            )

    if re.search(r"加税|加征|增税", text):
        return FreeformResult(
            effects={"global.national_treasury": 30, "global.civil_morale": -10},
            narrative="朕下旨加征赋税，国库稍有充盈，然百姓多有怨言。",
            rationale="加税",
        )

    if re.search(r"减税|免税|降税", text):
        return FreeformResult(
            effects={"global.national_treasury": -20, "global.civil_morale": 10},
            narrative="朕体恤百姓，减免赋税，民心稍安。",
            rationale="减税",
        )

    region_match = REGION_KEYWORDS.search(text)
    if re.search(r"赈灾|赈济|救灾", text) and region_match:
        rname = region_match.group(0)
        return FreeformResult(
            effects={"global.national_treasury": -30, f"region.{rname}.disaster_level": -15},
            narrative=f"朕拨银赈济{rname}，灾民感恩戴德。",
            rationale=f"赈济{rname}",
        )

    return parse_error("无法识别具体政务意图")


def rule_classify_chat_intent(
    text: str,
    game_state: GameState,
    conversation_history: list[dict],
) -> dict:
    normalized = (text or "").strip()
    if not normalized:
        return {
            "intent": "execute",
            "confidence": 0.0,
            "reason": "输入为空，默认执行分支",
        }

    if normalized.startswith(EXPLORE_PREFIX):
        return {
            "intent": "query",
            "confidence": 1.0,
            "reason": "命中探索前缀，强制查询分支",
        }

    if re.search(r"进入下月|下个月|翻月|推进月份|进入次月", normalized):
        return {
            "intent": "advance_month",
            "confidence": 0.95,
            "reason": "匹配到翻月关键词",
        }

    if re.search(
        r"多少|几|何|查询|查看|状态|在朝|国库|民心|军心|年月|时间|有哪些|谁在|局势|介绍|分析|背景",
        normalized,
    ):
        return {
            "intent": "query",
            "confidence": 0.9,
            "reason": "匹配到查询关键词",
        }

    if re.search(r"加税|减税|征兵|募兵|裁兵|任命|罢免|赈灾|外交|严刑|处决|斩", normalized):
        return {
            "intent": "execute",
            "confidence": 0.9,
            "reason": "匹配到执行关键词",
        }

    return {
        "intent": "execute",
        "confidence": 0.55,
        "reason": "意图不明，默认执行分支",
    }


def rule_chat_query(
    text: str,
    game_state: GameState,
    conversation_history: list[dict],
) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return "主公，臣在。"

    if re.search(r"国库|银两|钱粮|钱", normalized):
        return f"主公，今国库尚存{game_state.national_treasury}万两，内帑{game_state.imperial_treasury}万两。"

    if re.search(r"民心|军心|威望", normalized):
        return (
            f"主公，当前民心{game_state.civil_morale}，"
            f"军心{game_state.military_morale}，朝廷威望{game_state.court_prestige}。"
        )

    if re.search(r"在朝|大臣|谁在", normalized):
        active = [m.name for m in game_state.ministers if m.status.value == "active"]
        roster = "、".join(active[:12]) if active else "暂无在朝大臣"
        return f"主公，今在朝诸臣为：{roster}。"

    if re.search(r"年月|时间|几月|何时", normalized):
        return f"主公，今为{game_state.time.year}年{game_state.time.month}月。"

    if re.search(r"事件|局势|大事", normalized):
        events = [e.name for e in game_state.active_events[:6]]
        if events:
            return f"主公，当前朝局要事有：{'、'.join(events)}。"
        return "主公，今暂无急报大事。"

    return "主公，此问臣已记下。就现有军报观之，宜稳国库、抚民心、振军纪，以待后图。"


def rule_minister_dialogue(
    minister: Minister,
    message: str,
    game_state: GameState,
    conversation_history: list[dict],
) -> dict:
    # A rule fallback must not invent a hidden random state change. Provider
    # adjudication may still return an explicit, validated loyalty delta.
    loyalty_change = 0
    mood = "neutral"

    if minister.faction == "淮西勋将":
        reply = f"臣{minister.name}谨遵将令。然臣以为此事关乎社稷，望主公三思而后行。"
    elif minister.faction == "幕府文臣":
        reply = f"臣{minister.name}叩首。主公圣明，臣当竭力奉行。"
    else:
        reply = f"臣{minister.name}领旨。臣当尽心竭力，不负主公厚望。"

    return {"reply": reply, "loyalty_change": loyalty_change, "mood": mood}
