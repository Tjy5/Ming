from __future__ import annotations

import re
from collections.abc import AsyncIterator

from models.game import (
    DebateResult,
    FreeformResult,
    GameState,
    MemorialDraft,
    Minister,
    MinisterReaction,
    StructuredDecree,
)
from models.enums import DecreeType, PersonnelAction

from .base import (
    AIProvider,
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
    DecreeType.TAX_INCREASE: "陛下，民心已然不稳，再加赋税恐激民变。臣请陛下三思。",
    DecreeType.TAX_DECREASE: "陛下，国库空虚，实难再减赋税。臣请陛下先充实国库。",
    DecreeType.RECRUIT_TROOPS: "陛下，钱粮或人口不足，难以征兵。臣请陛下筹措资源后再议。",
    DecreeType.DISBAND_TROOPS: "陛下，军备不足，裁兵恐致边防空虚。臣请陛下慎重。",
    DecreeType.PERSONNEL: "陛下，朝廷威望不足以服众，此时人事变动恐生乱象。",
    DecreeType.DIPLOMACY: "陛下，国库不足以支撑外交使费。臣请陛下先充实国库。",
    DecreeType.DISASTER_RELIEF: "陛下，国库仅余有限银两，实难拨付赈灾银两。臣请陛下先充实国库，再议赈济之事。",
    DecreeType.HARSH_PUNISHMENT: "陛下，朝廷威望不足，严刑峻法恐适得其反。",
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

REGION_KEYWORDS = re.compile(r"京畿|辽东|陕西|江南|中原|山东|云贵|川蜀")
DIPLOMACY_KEYWORDS = re.compile(r"后金|蒙古|朝鲜")
PERSON_PATTERN = re.compile(r"(?:把|将|令|命)?([^\s,，。、]{2,4})(?:调|贬|擢|免|罢|任|撤)")
_VACANCY_HINTS = ("空缺", "继任", "补缺", "替补", "vacancy")


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


class MockProvider(AIProvider):
    async def generate_narrative(
        self,
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

    async def stream_narrative(
        self,
        delta_attribution: dict,
        game_state: GameState,
        chain_events: list[str],
        decree: StructuredDecree,
    ) -> AsyncIterator[str]:
        narrative = await self.generate_narrative(delta_attribution, game_state, chain_events, decree)
        if narrative:
            yield narrative

    async def parse_free_input(
        self,
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

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        return REJECTION_TEMPLATES.get(decree.type, f"陛下，此令无法执行：{reason}")

    async def generate_debate_narrative(
        self,
        topic: str,
        minister_a: Minister,
        minister_b: Minister,
        game_state: GameState,
    ) -> DebateResult | None:
        return None



    async def generate_memorial(
        self,
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

        content = f"臣{author.name}伏惟陛下圣鉴：{trigger_reason}事关社稷安危，臣不敢不奏。伏乞圣裁。"
        return MemorialDraft(content=content, suggested_decrees=decrees)

    async def generate_minister_reaction(
        self,
        minister: Minister,
        decree: StructuredDecree,
        stance: int,
        game_state: GameState,
    ) -> str:
        if stance > 0:
            return f"{minister.name}拱手道：陛下圣明。"
        return f"{minister.name}跪奏：臣以为此举不妥，恳请陛下三思。"

    async def generate_assembly_debate(
        self,
        topic: str,
        participants: list[Minister],
        game_state: GameState,
    ) -> dict | None:
        speeches = await self.generate_debate_speeches(topic, participants, game_state)
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
                    "description": "请陛下依朝议结果酌定施行。",
                    "decree_type": decree_type.value,
                    "supporter_names": supporters[:8],
                }
            ],
            "consensus": consensus,
            "speeches": speeches,
        }

    async def generate_action_implications(
        self,
        summary_data: dict,
        game_state: GameState,
    ) -> list[str]:
        rule_based = summary_data.get("rule_based_implications", [])
        return [str(x) for x in (rule_based or [])][:3]

    async def generate_turn_commentary(
        self,
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

    async def classify_script_choice(
        self,
        player_text: str,
        script_context: dict | None = None,
        *,
        game_state: GameState | None = None,
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

    async def select_script_trigger_decisions(
        self,
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

    async def process_freeform(
        self,
        text: str,
        game_state: GameState,
        *,
        script_context: dict | None = None,
    ) -> FreeformResult | dict:
        minister_names = {m.name for m in game_state.ministers if m.status.value != "removed"}

        for pat in (EXECUTION_PREFIX_RE, EXECUTION_SUFFIX_RE):
            match = pat.search(text)
            if match and match.group(1) in minister_names:
                name = match.group(1)
                return FreeformResult(
                    effects={f"minister.{name}.status": "removed"},
                    narrative=f"陛下龙颜大怒，下旨将{name}押赴刑场，斩首示众。",
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

    async def generate_minister_dialogue(
        self,
        minister: Minister,
        message: str,
        game_state: GameState,
        conversation_history: list[dict],
    ) -> dict:
        import random

        loyalty_change = random.randint(-1, 1)
        if loyalty_change > 0:
            mood = "support"
        elif loyalty_change < 0:
            mood = "oppose"
        else:
            mood = "neutral"

        if minister.faction == "东林党":
            reply = f"臣{minister.name}谨遵圣旨。然臣以为此事关乎社稷，望陛下三思而后行。"
        elif minister.faction == "阉党残余":
            reply = f"臣{minister.name}叩首。陛下圣明，臣当竭力奉行。"
        else:
            reply = f"臣{minister.name}领旨。臣当尽心竭力，不负陛下厚望。"

        return {"reply": reply, "loyalty_change": loyalty_change, "mood": mood}
