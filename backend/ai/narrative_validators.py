"""Narrative-visible validation over committed sibling facts.

Gameplay proposal/entity/death validation remains owned by sandbox modules.
This module only decides whether a text may be displayed for an already chosen
context and settlement.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from ai.narrative_context import NarrativeContext
from engine.numeric_bands import active_threshold_alerts
from engine.state_consistency import validate_narrative_text
from models.game import GameState
from models.settlement import PlayerWorldDelta


class NarrativeFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    sentence: str | None = None
    fact_reference: str | None = None


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")
_ACTIVE_VERBS = (
    "说道", "上奏", "进言", "主持", "执行", "率军", "领兵", "奉命",
    "接管", "出使", "担任", "执掌", "下令",
)
_ROLL_WORDS = (
    "掷骰", "骰点", "D100", "d100", "大失败", "大成功", "重掷",
    "运气", "侥幸", "走运", "随机波动",
)
_DEATH_WORDS = (
    "主角死亡", "主角身亡", "主角驾崩", "主角战死", "主角殒命",
    "身死", "殒没", "困毙", "游戏结束", "此局已终", "终局已至",
)
_DEATH_CAUSE_RE = re.compile(
    r"(?:直接死因|死因|因果摘要)[：:](?P<value>[^。！？!?；;]+)",
)
_FUTURE_COMPLETE_WORDS = ("已经完成", "已全部完成", "大功告成", "如期完成")
_ROLL_VALUE_RE = re.compile(r"(?:D100|d100|掷骰|骰点)[^0-9]{0,8}(\d{1,3})")
_ROLL_TARGET_RE = re.compile(r"目标(?:值)?[^0-9]{0,6}(\d{1,3})")
_ROLL_MODIFIER_BLOCK_RE = re.compile(
    r"修正(?:为|：|:)\s*(?P<body>[^。！？!?；;]*?)"
    r"(?=，?结果(?:为|：|:)?|[。！？!?；;]|$)",
)
_ROLL_MODIFIER_RE = re.compile(r"(?P<name>[^、，,\s:+\-]+)\s*(?P<value>[+\-]\d+)")
_ROLL_TIER_RE = re.compile(
    r"结果(?:为|：|:)?\s*(critical_success|critical_failure|partial_success|success|failure|大成功|大失败|成功|失败)",
)
_CURRENT_DATE_RE = re.compile(
    r"(?:当前|如今|时值|此时)[^。！？!?；;]{0,16}?(?P<year>\d{3,4})年"
    r"(?:(?P<month>\d{1,2})月(?:(?P<day>\d{1,2})日)?)?",
)
_WORLD_CLOCK_RE = re.compile(
    r"世界时钟已推进至(?P<era>[^0-9。！？!?；;]{0,16}?)"
    r"(?P<era_year>\d{1,4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
    r"(?P<double_hour>[^。！？!?；;]*)",
)
_FACT_LABEL_RE = re.compile(
    r"(?P<label>关键依据|已生效变化|已生效结果|跨越事件)[：:]"
    r"(?P<value>[^。！？!?]+)",
)
_EXECUTOR_LABEL_RE = re.compile(
    r"(?P<label>请求执行者|实际执行者)[：:]\s*(?P<value>[^，,。！？!?；;]+)",
)
_EXECUTION_STATUS_RE = re.compile(
    r"执行状态[：:]\s*(?P<value>[^，,。！？!?；;]+)",
)
_ACTIVITY_STATUS_RE = re.compile(
    r"(?:当前)?活动状态[：:]\s*(?P<value>[^，,。！？!?；;]+)",
)
_CHECKPOINT_SEQUENCE_RE = re.compile(r"检查点(?:序号)?[：:]?\s*(\d+)")
_REMAINING_HOURS_RE = re.compile(r"剩余(?:时长)?[：:]?\s*(\d+)小时")
_ELAPSED_HOURS_RE = re.compile(r"(?:已经|已)?用时[：:]?\s*(\d+)小时")
_ACTIVITY_INTERRUPTION_RE = re.compile(
    r"活动中断依据[：:](?P<value>[^。！？!?]+)",
)
_METRIC_BAND_RE = re.compile(
    r"(?P<metric>[A-Za-z_][A-Za-z0-9_]*|国库|内帑|粮草|人口|军力|民心|军心|朝廷威望)"
    r"(?:的)?(?P<kind>基础|有效)档位(?:为|：|:)?\s*(?P<band>[^\s，,。！？!?；;]+)",
)

_RESULT_TIER_CLAIMS = {
    "行动取得重大成功": "success",
    "行动部分成功": "partial_success",
    "行动未达预期": "failure",
    "行动遭遇重大失败": "failure",
    "行动成功": "success",
    "行动失败": "failure",
}
_ROLL_TIER_ALIASES = {
    "大成功": "critical_success",
    "成功": "success",
    "失败": "failure",
    "大失败": "critical_failure",
}
_EXECUTION_STATUS_ALIASES = {
    "未尝试": "not_attempted",
    "已尝试": "attempted",
    "已完成": "completed",
    "完成": "completed",
    "受阻": "blocked",
    "被阻止": "blocked",
    "失败": "failed",
}
_ACTIVITY_STATUS_ALIASES = {
    "进行中": "in_progress",
    "等待玩家决定": "awaiting_player_decision",
    "暂停": "paused",
    "已取消": "cancelled",
    "失败": "failed",
    "已完成": "completed",
}
_EXECUTOR_ACTION_VERBS = ("执行", "奉命", "率军", "领兵", "接管", "出使", "执掌")
_NEGATED_EXECUTION_WORDS = ("拒绝", "未执行", "没有执行", "无法执行", "未能执行")
_COMPLETED_EXECUTION_WORDS = ("执行完成", "完成执行", "奉命完成", "已执行", "已办妥")
_DEAD_CONTINUATION_WORDS = (
    "主角复活", "主角苏醒", "死而复生", "主角继续行动", "主角仍可行动",
    "继续下一回合", "世界线继续", "由继承人继续", "继承主角", "切换视角", "换视角",
)
_METRIC_LABELS = {
    "国库": "national_treasury",
    "内帑": "imperial_treasury",
    "粮草": "grain",
    "人口": "population",
    "军力": "military_strength",
    "民心": "civil_morale",
    "军心": "military_morale",
    "朝廷威望": "court_prestige",
}
_FACT_SECTION_LABELS = {
    "关键依据",
    "已生效变化",
    "已生效结果",
    "后续风险",
    "新机会",
    "公开检定",
    "结算编号",
    "当前活动状态",
    "检查点序号",
    "已用时",
    "剩余时长",
    "跨越事件",
    "活动中断依据",
}
_THRESHOLD_TONE_CONTRADICTIONS = {
    "民心崩溃预警": (
        "歌舞升平", "民心安泰", "民心稳固", "百姓安居", "秩序井然", "天下太平",
    ),
    "军心动摇预警": ("士气高昂", "军令严明", "军心稳固", "士卒用命"),
    "国库空虚预警": ("大兴土木", "挥霍无度", "财力充盈", "国库充盈"),
    "叛乱高危预警": ("上下同欲", "朝局稳固", "人心归附"),
    "区域失稳预警": ("安居乐业", "秩序井然", "地方安宁", "四境安定"),
}
_THRESHOLD_NEGATIONS = (
    "不", "未", "非", "无", "不是", "并非", "绝非", "并不", "未见", "不见",
    "难言", "不可谓", "不能说", "不能说是",
)


def iter_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for paragraph in (text or "").replace("\r\n", "\n").split("\n"):
        for part in _SENTENCE_SPLIT_RE.split(paragraph):
            item = part.strip()
            if item:
                sentences.append(item)
    return sentences


def _committed_death_deltas(context: NarrativeContext) -> list[PlayerWorldDelta]:
    if context.settlement is None:
        return []
    return [
        delta
        for delta in context.settlement.deltas
        if isinstance(delta, PlayerWorldDelta) and delta.operation == "death"
    ]


def sentence_chunks(text: str) -> list[str]:
    return iter_sentences(text)


def _dynamic_entity_names(context: NarrativeContext) -> set[str]:
    return {entity.display_name for entity in context.entities}


def _legacy_findings(
    text: str,
    context: NarrativeContext,
    state: GameState,
) -> list[NarrativeFinding]:
    dynamic_names = _dynamic_entity_names(context)
    findings: list[NarrativeFinding] = []
    for issue in validate_narrative_text(text, state):
        actor = str(issue.get("actor") or "")
        # The legacy facade still uses a static minister roster.  A committed
        # dynamic registry identity is valid narrative input and must not be
        # rejected as an invented speaker. Deterministic facts-fallback section
        # labels also use a colon, but are not dialogue speakers.
        if issue.get("type") in {"invented_speaker", "invented_court_actor"}:
            if actor in dynamic_names or actor in _FACT_SECTION_LABELS:
                continue
        findings.append(
            NarrativeFinding(
                code=str(issue.get("type") or "legacy_consistency"),
                message=str(issue.get("reason") or "叙事与当前状态不一致"),
                sentence=str(issue.get("sentence") or "") or None,
                fact_reference=f"entity:{actor}" if actor else None,
            ),
        )
    return findings


def _threshold_phrase_is_negated(sentence: str, phrase_index: int) -> bool:
    prefix = sentence[max(0, phrase_index - 8):phrase_index].rstrip()
    return any(prefix.endswith(marker) for marker in _THRESHOLD_NEGATIONS)


def _threshold_tone_findings(text: str, state: GameState) -> list[NarrativeFinding]:
    findings: list[NarrativeFinding] = []
    sentences = iter_sentences(text)
    for alert_name, constraint in active_threshold_alerts(state):
        contradictions = _THRESHOLD_TONE_CONTRADICTIONS.get(alert_name, ())
        for sentence in sentences:
            violating_phrase = next(
                (
                    phrase
                    for phrase in contradictions
                    if (index := sentence.find(phrase)) >= 0
                    and not _threshold_phrase_is_negated(sentence, index)
                ),
                None,
            )
            if violating_phrase is None:
                continue
            findings.append(NarrativeFinding(
                code="threshold_tone_violation",
                message=f"叙事违反{alert_name}：{constraint}",
                sentence=sentence,
                fact_reference=f"threshold:{alert_name}",
            ))
    return findings


def _normalized_claim(value: str) -> str:
    return value.strip().strip("‘’“”\"' ")


def _settlement_claim_findings(
    sentence: str,
    context: NarrativeContext,
) -> list[NarrativeFinding]:
    facts = context.settlement
    if facts is None:
        return []
    reference = f"settlement:{context.settlement_id}"
    findings: list[NarrativeFinding] = []
    for claim, tier in _RESULT_TIER_CLAIMS.items():
        if claim in sentence and tier != facts.result_tier:
            findings.append(NarrativeFinding(
                code="settlement_result_tier_mismatch",
                message="叙事结果档位与已提交结算不一致",
                sentence=sentence,
                fact_reference=f"{reference}:result_tier",
            ))
            break

    committed_by_label = {
        "关键依据": set(facts.key_factors),
        "已生效变化": set(facts.immediate_changes),
        "已生效结果": {facts.actual_outcome} if facts.actual_outcome else set(),
        "跨越事件": set(facts.crossed_events),
    }
    code_by_label = {
        "关键依据": "uncommitted_key_factor",
        "已生效变化": "uncommitted_immediate_change",
        "已生效结果": "actual_outcome_mismatch",
        "跨越事件": "uncommitted_crossed_event",
    }
    for match in _FACT_LABEL_RE.finditer(sentence):
        label = match.group("label")
        claims = {
            _normalized_claim(item)
            for item in re.split(r"[；;]", match.group("value"))
            if _normalized_claim(item)
        }
        uncommitted = claims - committed_by_label[label]
        if uncommitted:
            findings.append(NarrativeFinding(
                code=code_by_label[label],
                message=f"{label}包含未提交事实：{'；'.join(sorted(uncommitted))}",
                sentence=sentence,
                fact_reference=f"{reference}:{label}",
            ))
    return findings


def _executor_claim_findings(
    sentence: str,
    context: NarrativeContext,
) -> list[NarrativeFinding]:
    facts = context.settlement
    if facts is None:
        return []
    attribution = facts.attribution
    entity_by_id = {entity.entity_id: entity for entity in context.entities}
    expected_ids = {
        "请求执行者": attribution.requested_executor_id,
        "实际执行者": attribution.actual_executor_id,
    }
    findings: list[NarrativeFinding] = []
    for match in _EXECUTOR_LABEL_RE.finditer(sentence):
        label = match.group("label")
        claimed = _normalized_claim(match.group("value"))
        entity_id = expected_ids[label]
        expected = entity_by_id.get(entity_id) if entity_id is not None else None
        expected_name = expected.display_name if expected is not None else None
        if label == "实际执行者" and expected_name is None and context.executor is not None:
            expected_name = context.executor.display_name
        allowed_claims = (
            {expected_name}
            if expected_name is not None
            else {"无", "无人", "未指定"}
        )
        if claimed not in allowed_claims:
            findings.append(NarrativeFinding(
                code=(
                    "requested_executor_mismatch"
                    if label == "请求执行者"
                    else "actual_executor_mismatch"
                ),
                message=f"{label}与已提交执行归因不一致",
                sentence=sentence,
                fact_reference=f"settlement:{context.settlement_id}:executor",
            ))

    status_match = _EXECUTION_STATUS_RE.search(sentence)
    if status_match is not None:
        claimed_status = _normalized_claim(status_match.group("value"))
        claimed_status = _EXECUTION_STATUS_ALIASES.get(claimed_status, claimed_status)
        if claimed_status != attribution.execution_status:
            findings.append(NarrativeFinding(
                code="execution_status_mismatch",
                message="叙事执行状态与已提交执行归因不一致",
                sentence=sentence,
                fact_reference=f"settlement:{context.settlement_id}:executor",
            ))

    if (
        attribution.execution_status in {"not_attempted", "blocked", "failed"}
        and any(word in sentence for word in _COMPLETED_EXECUTION_WORDS)
    ):
        findings.append(NarrativeFinding(
            code="execution_status_mismatch",
            message="叙事将未完成的执行宣称为已经完成",
            sentence=sentence,
            fact_reference=f"settlement:{context.settlement_id}:executor",
        ))

    actual_id = attribution.actual_executor_id
    has_negation = any(word in sentence for word in _NEGATED_EXECUTION_WORDS)
    if _EXECUTOR_LABEL_RE.search(sentence) is None:
        for entity in context.entities:
            if (
                entity.display_name in sentence
                and any(verb in sentence for verb in _EXECUTOR_ACTION_VERBS)
                and not has_negation
                and entity.entity_id != actual_id
            ):
                findings.append(NarrativeFinding(
                    code="unauthorized_executor_claim",
                    message=f"{entity.display_name}不是本次结算的实际执行者",
                    sentence=sentence,
                    fact_reference=f"entity:{entity.entity_id}",
                ))
    return findings


def _roll_claim_findings(
    sentence: str,
    context: NarrativeContext,
) -> list[NarrativeFinding]:
    facts = context.settlement
    if facts is None:
        return []
    committed_rolls = list(facts.rolls)
    reference = f"settlement:{context.settlement_id}:roll"
    findings: list[NarrativeFinding] = []
    if not committed_rolls:
        if any(word in sentence for word in _ROLL_WORDS):
            findings.append(NarrativeFinding(
                code="uncommitted_roll",
                message="当前结算不存在公开骰点",
                sentence=sentence,
                fact_reference=reference,
            ))
        return findings

    if "重掷" in sentence:
        findings.append(NarrativeFinding(
            code="uncommitted_reroll",
            message="当前结算只允许引用已提交的公开检定，不存在重掷事实",
            sentence=sentence,
            fact_reference=reference,
        ))

    matching_rolls = committed_rolls
    roll_matches = list(_ROLL_VALUE_RE.finditer(sentence))
    roll_match = roll_matches[0] if roll_matches else None
    if roll_matches:
        raw_values = [int(match.group(1)) for match in roll_matches]
        raw_value = raw_values[0]
        matching_rolls = [roll for roll in matching_rolls if roll.raw_d100 == raw_value]
        if (
            not matching_rolls
            or any(value not in {roll.raw_d100 for roll in committed_rolls} for value in raw_values)
        ):
            findings.append(NarrativeFinding(
                code="roll_raw_mismatch",
                message="叙事骰点与已提交公开检定不一致",
                sentence=sentence,
                fact_reference=reference,
            ))

    target_match = _ROLL_TARGET_RE.search(sentence)
    if target_match is not None:
        target_value = int(target_match.group(1))
        target_rolls = [
            roll for roll in matching_rolls
            if roll.target_value == target_value
        ]
        if not target_rolls:
            findings.append(NarrativeFinding(
                code="roll_target_mismatch",
                message="叙事目标值与已提交公开检定不一致",
                sentence=sentence,
                fact_reference=reference,
            ))
        matching_rolls = target_rolls

    roll_claim = any(word in sentence for word in _ROLL_WORDS) or roll_match is not None
    tier_match = _ROLL_TIER_RE.search(sentence) if roll_claim else None
    if tier_match is not None:
        claimed_tier = tier_match.group(1)
        claimed_tier = _ROLL_TIER_ALIASES.get(claimed_tier, claimed_tier)
        if not any(roll.result_tier == claimed_tier for roll in matching_rolls):
            findings.append(NarrativeFinding(
                code="roll_result_tier_mismatch",
                message="叙事检定档位与已提交公开检定不一致",
                sentence=sentence,
                fact_reference=reference,
            ))

    modifier_match = _ROLL_MODIFIER_BLOCK_RE.search(sentence) if roll_claim else None
    if modifier_match is not None:
        body = modifier_match.group("body").strip()
        claimed_modifiers = sorted(
            (item.group("name"), int(item.group("value")))
            for item in _ROLL_MODIFIER_RE.finditer(body)
        )
        if "无公开修正" in body:
            claimed_modifiers = []
        exact_modifier_match = any(
            claimed_modifiers == sorted(
                (modifier.name, modifier.value) for modifier in roll.modifiers
            )
            for roll in matching_rolls
        )
        if not exact_modifier_match:
            findings.append(NarrativeFinding(
                code="roll_modifier_mismatch",
                message="叙事公开修正与已提交检定不一致",
                sentence=sentence,
                fact_reference=reference,
            ))
    return findings


def _time_activity_and_band_findings(
    sentence: str,
    context: NarrativeContext,
) -> list[NarrativeFinding]:
    findings: list[NarrativeFinding] = []
    calendar = context.time.calendar
    date_match = _CURRENT_DATE_RE.search(sentence)
    if date_match is not None:
        month = date_match.group("month")
        day = date_match.group("day")
        if (
            int(date_match.group("year")) != calendar.year
            or (month is not None and int(month) != calendar.month)
            or (day is not None and int(day) != calendar.day)
        ):
            findings.append(NarrativeFinding(
                code="current_time_mismatch",
                message="叙事中的当前日期与世界时钟不一致",
                sentence=sentence,
                fact_reference=f"version:{context.version_id}",
            ))

    clock_match = _WORLD_CLOCK_RE.search(sentence)
    if clock_match is not None:
        double_hour = clock_match.group("double_hour").strip()
        if (
            clock_match.group("era").strip() != calendar.era_name
            or int(clock_match.group("era_year")) != calendar.era_year
            or int(clock_match.group("month")) != calendar.month
            or int(clock_match.group("day")) != calendar.day
            or (double_hour and double_hour != calendar.double_hour_name)
        ):
            findings.append(NarrativeFinding(
                code="world_clock_mismatch",
                message="叙事中的推进后时钟与已提交版本不一致",
                sentence=sentence,
                fact_reference=f"version:{context.version_id}:calendar",
            ))

    metric_by_key = {
        metric.target.metric_key: metric for metric in context.world_state.metrics
    }
    for match in _METRIC_BAND_RE.finditer(sentence):
        metric_key = _METRIC_LABELS.get(match.group("metric"), match.group("metric"))
        metric = metric_by_key.get(metric_key)
        if metric is None:
            continue
        kind = "base_band" if match.group("kind") == "基础" else "effective_band"
        if match.group("band") != getattr(metric, kind):
            findings.append(NarrativeFinding(
                code="numeric_band_mismatch",
                message="叙事数值档位与当前版本投影不一致",
                sentence=sentence,
                fact_reference=f"metric:{metric_key}:{kind}",
            ))

    activity = context.current_activity
    if activity is not None:
        status_match = _ACTIVITY_STATUS_RE.search(sentence)
        if status_match is not None:
            claimed_status = _normalized_claim(status_match.group("value"))
            claimed_status = _ACTIVITY_STATUS_ALIASES.get(claimed_status, claimed_status)
            if claimed_status != activity.status:
                findings.append(NarrativeFinding(
                    code="activity_status_mismatch",
                    message="叙事活动状态与已提交检查点不一致",
                    sentence=sentence,
                    fact_reference=f"activity:{activity.activity_id}",
                ))
        checkpoint_match = _CHECKPOINT_SEQUENCE_RE.search(sentence)
        if (
            checkpoint_match is not None
            and int(checkpoint_match.group(1)) != activity.checkpoint_sequence
        ):
            findings.append(NarrativeFinding(
                code="activity_checkpoint_mismatch",
                message="叙事检查点序号与已提交事实不一致",
                sentence=sentence,
                fact_reference=f"activity:{activity.activity_id}:checkpoint",
            ))
        remaining_match = _REMAINING_HOURS_RE.search(sentence)
        if (
            remaining_match is not None
            and int(remaining_match.group(1)) != activity.remaining_hours
        ):
            findings.append(NarrativeFinding(
                code="activity_remaining_time_mismatch",
                message="叙事剩余时长与已提交活动事实不一致",
                sentence=sentence,
                fact_reference=f"activity:{activity.activity_id}:remaining_hours",
            ))
        elapsed_match = _ELAPSED_HOURS_RE.search(sentence)
        if (
            elapsed_match is not None
            and int(elapsed_match.group(1)) != activity.elapsed_hours
        ):
            findings.append(NarrativeFinding(
                code="activity_elapsed_time_mismatch",
                message="叙事已用时与已提交活动事实不一致",
                sentence=sentence,
                fact_reference=f"activity:{activity.activity_id}:elapsed_hours",
            ))
        interruption_match = _ACTIVITY_INTERRUPTION_RE.search(sentence)
        if interruption_match is not None:
            claims = {
                _normalized_claim(item)
                for item in re.split(r"[；;]", interruption_match.group("value"))
                if _normalized_claim(item)
            }
            if claims - set(activity.interruption_facts):
                findings.append(NarrativeFinding(
                    code="activity_interruption_mismatch",
                    message="叙事中断依据包含未提交的活动事实",
                    sentence=sentence,
                    fact_reference=f"activity:{activity.activity_id}:interruptions",
                ))
        if (
            activity.status not in {"completed", "cancelled", "failed"}
            and any(word in sentence for word in _FUTURE_COMPLETE_WORDS)
            and (activity.intent in sentence or "活动" in sentence or "长期任务" in sentence)
        ):
            findings.append(NarrativeFinding(
                code="future_activity_completion",
                message="叙事提前宣称尚未完成的长期活动已结束",
                sentence=sentence,
                fact_reference=f"activity:{activity.activity_id}",
            ))
    return findings


def validate_narrative_candidate(
    text: str,
    *,
    context: NarrativeContext,
    state: GameState,
    forbidden_claims: list[str] | None = None,
) -> list[NarrativeFinding]:
    candidate = (text or "").strip()
    if not candidate:
        return [NarrativeFinding(code="empty_narrative", message="模型未返回叙事文本")]

    findings = _legacy_findings(candidate, context, state)
    findings.extend(_threshold_tone_findings(candidate, state))
    sentences = iter_sentences(candidate)
    entity_by_name = {entity.display_name: entity for entity in context.entities}
    for sentence in sentences:
        for name, entity in entity_by_name.items():
            if (
                entity.status != "active" or not entity.available
            ) and name in sentence and any(verb in sentence for verb in _ACTIVE_VERBS):
                findings.append(
                    NarrativeFinding(
                        code="inactive_entity_activity",
                        message=f"{name}在当前版本不可行动",
                        sentence=sentence,
                        fact_reference=f"entity:{entity.entity_id}",
                    ),
                )

        if context.player.life_status != "dead" and any(
            word in sentence for word in _DEATH_WORDS
        ):
            findings.append(
                NarrativeFinding(
                    code="uncommitted_player_death",
                    message="主角死亡尚未作为 settlement facts 提交",
                    sentence=sentence,
                    fact_reference=f"version:{context.version_id}",
                ),
            )
        if context.player.life_status == "dead" and any(
            word in sentence for word in _DEAD_CONTINUATION_WORDS
        ):
            findings.append(
                NarrativeFinding(
                    code="dead_player_continuation",
                    message="主角死亡后的复活或继续行动没有已提交事实依据",
                    sentence=sentence,
                    fact_reference=f"version:{context.version_id}:player",
                ),
            )

        findings.extend(_settlement_claim_findings(sentence, context))
        findings.extend(_executor_claim_findings(sentence, context))
        findings.extend(_roll_claim_findings(sentence, context))
        findings.extend(_time_activity_and_band_findings(sentence, context))

        for claim in forbidden_claims or []:
            if claim and claim in sentence:
                findings.append(
                    NarrativeFinding(
                        code="uncommitted_effect",
                        message="叙事引用了未落库或被拒绝的变化",
                        sentence=sentence,
                        fact_reference=f"forbidden-claim:{claim}",
                    ),
                )

    death_deltas = _committed_death_deltas(context)
    if context.player.life_status == "dead":
        if len(death_deltas) != 1:
            findings.append(
                NarrativeFinding(
                    code="terminal_facts_missing",
                    message="死亡状态缺少唯一的已提交 death delta",
                    fact_reference=f"version:{context.version_id}:player",
                ),
            )
        else:
            death = death_deltas[0]
            has_terminal_wording = any(word in candidate for word in _DEATH_WORDS)
            allowed_causes = {
                _normalized_claim(value)
                for value in [
                    death.direct_cause or "",
                    death.causal_summary or "",
                    *death.key_factors,
                ]
                if _normalized_claim(value)
            }
            normalized_candidate = _normalized_claim(candidate)
            has_committed_cause = any(
                cause in normalized_candidate for cause in allowed_causes
            )
            if not has_terminal_wording:
                findings.append(
                    NarrativeFinding(
                        code="committed_player_death_omitted",
                        message="终局叙事遗漏了已提交的主角死亡事实",
                        fact_reference=f"settlement:{context.settlement_id}:death",
                    ),
                )
            if not has_committed_cause:
                findings.append(
                    NarrativeFinding(
                        code="player_death_cause_missing",
                        message="终局叙事未承接已提交的直接死因或关键因子",
                        fact_reference=f"settlement:{context.settlement_id}:death",
                    ),
                )
            for match in _DEATH_CAUSE_RE.finditer(candidate):
                claim = _normalized_claim(match.group("value"))
                if claim not in allowed_causes:
                    findings.append(
                        NarrativeFinding(
                            code="player_death_cause_mismatch",
                            message="终局叙事声称了未提交的死因或因果摘要",
                            sentence=next(
                                (sentence for sentence in sentences if match.group(0) in sentence),
                                None,
                            ),
                            fact_reference=f"settlement:{context.settlement_id}:death",
                        ),
                    )
    elif death_deltas:
        findings.append(
            NarrativeFinding(
                code="terminal_state_mismatch",
                message="settlement 含死亡 delta，但当前玩家状态仍为存活",
                fact_reference=f"settlement:{context.settlement_id}:death",
            ),
        )

    # Preserve deterministic order while removing duplicate reports generated
    # by overlapping legacy and dynamic checks.
    unique: dict[tuple[str, str | None, str | None], NarrativeFinding] = {}
    for finding in findings:
        unique[(finding.code, finding.sentence, finding.fact_reference)] = finding
    return list(unique.values())


def build_repair_instruction(findings: list[NarrativeFinding]) -> str:
    lines = ["重写整段叙事，只描述给定当前版本与已提交结算事实。必须修复："]
    for finding in findings:
        lines.append(f"- [{finding.code}] {finding.message}")
    lines.append("不得输出原始推理；无法安全重写时只复述结构化事实。")
    return "\n".join(lines)


def facts_narrative(context: NarrativeContext) -> str:
    facts = context.settlement
    if facts is None:
        calendar = context.time.calendar
        return (
            f"当前为{calendar.era_name}{calendar.era_year}年"
            f"{calendar.month}月{calendar.day}日，世界状态保持可继续行动。"
        )

    tier_labels = {
        "success": "行动成功",
        "partial_success": "行动部分成功",
        "failure": "行动未达预期",
        "critical_success": "行动取得重大成功",
        "critical_failure": "行动遭遇重大失败",
    }
    parts = [tier_labels.get(str(facts.result_tier), "行动已结算") + "。"]
    if facts.key_factors:
        parts.append("关键依据：" + "；".join(facts.key_factors) + "。")
    if facts.immediate_changes:
        parts.append("已生效变化：" + "；".join(facts.immediate_changes) + "。")
    elif facts.actual_outcome:
        parts.append("已生效结果：" + facts.actual_outcome + "。")
    if facts.time_plan is not None:
        end = facts.time_plan.normalized_duration.end_calendar
        parts.append(
            f"世界时钟已推进至{end.era_name}{end.era_year}年"
            f"{end.month}月{end.day}日{end.double_hour_name}。",
        )
    activity = context.current_activity
    if activity is not None:
        activity_parts = [
            f"当前活动状态：{activity.status}",
            f"已用时：{activity.elapsed_hours}小时",
            f"剩余时长：{activity.remaining_hours}小时",
        ]
        if activity.checkpoint_sequence is not None:
            activity_parts.insert(1, f"检查点序号：{activity.checkpoint_sequence}")
        parts.append("；".join(activity_parts) + "。")
        if activity.crossed_events:
            parts.append("跨越事件：" + "；".join(activity.crossed_events) + "。")
        if activity.interruption_facts:
            parts.append("活动中断依据：" + "；".join(activity.interruption_facts) + "。")
    if facts.long_term_risks:
        parts.append("后续风险：" + "；".join(facts.long_term_risks) + "。")
    if facts.new_opportunities:
        parts.append("新机会：" + "；".join(facts.new_opportunities) + "。")
    for roll in facts.rolls:
        modifier_text = "、".join(
            f"{modifier.name}{modifier.value:+d}" for modifier in roll.modifiers
        ) or "无公开修正"
        target_text = (
            f"，目标值{roll.target_value}" if roll.target_value is not None else ""
        )
        tier_text = f"，结果{roll.result_tier}" if roll.result_tier else ""
        parts.append(
            f"公开检定：D100骰点{roll.raw_d100}{target_text}，"
            f"修正为{modifier_text}{tier_text}。",
        )
    if context.player.life_status == "dead":
        death_deltas = _committed_death_deltas(context)
        if len(death_deltas) == 1:
            death = death_deltas[0]
            parts.append("直接死因：" + (death.direct_cause or "") + "。")
            parts.append("死亡关键因子：" + "；".join(death.key_factors) + "。")
            parts.append("因果摘要：" + (death.causal_summary or "") + "。")
        parts.append("主角死亡已作为本次结算事实提交，当前世界线在此终止。")
    parts.append(f"结算编号：{facts.settlement_id}。")
    return "".join(parts)


def sanitize_candidate(
    text: str,
    findings: list[NarrativeFinding],
    *,
    fallback: str,
) -> tuple[str, bool]:
    # Only local claims that can be removed without changing the committed
    # result are sanitizable.  Time/death/executor/roll/activity contradictions
    # are load-bearing; deleting them could invert the meaning of the result.
    removable_codes = {"uncommitted_effect", "inactive_entity_activity"}
    if any(finding.code not in removable_codes for finding in findings):
        return fallback, True
    flagged = {finding.sentence for finding in findings if finding.sentence}
    if not flagged:
        return fallback, True
    kept = [sentence for sentence in iter_sentences(text) if sentence not in flagged]
    cleaned = "".join(kept).strip()
    if len(cleaned) < 5:
        return fallback, True
    return cleaned, False
