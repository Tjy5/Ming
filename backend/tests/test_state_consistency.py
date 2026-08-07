"""状态一致性硬校验（08-07-state-consistency-verification）。

覆盖：硬状态源助手、叙事校验器（规则A/B）、净化兜底、prompt 守卫、
校验→重试→净化闭环、freeform 丢弃 effects 同源、流式/轻量路径。
"""
from __future__ import annotations

import pytest

from engine.state_consistency import (
    EXTERNAL_ENTITIES,
    FALLBACK_NARRATIVE,
    active_actor_names,
    build_prompt_guard,
    build_retry_instruction,
    ensure_narrative_consistent,
    roster_names,
    sanitize_ai_text,
    sanitize_narrative,
    unavailable_actors,
    validate_narrative_text,
    validation_log,
)
from engine.core import process_decree, validate_ai_effects
from models.game import (
    FreeformResult,
    GameState,
    GameTime,
    INITIAL_FACTIONS,
    INITIAL_MINISTERS,
    INITIAL_REGIONS,
    Minister,
    StructuredDecree,
)
from models.enums import DecreeType, MinisterStatus


# ── Helpers ──────────────────────────────────────────────

def make_state(**overrides) -> GameState:
    defaults = dict(
        time=GameTime(year=1360, month=6, era_name="至正", era_year=20),
        national_treasury=15, imperial_treasury=8, grain=420,
        population=1600, military_strength=18,
        civil_morale=62, military_morale=68, court_prestige=62,
        factions=[f.model_copy() for f in INITIAL_FACTIONS],
        regions=[r.model_copy() for r in INITIAL_REGIONS],
        ministers=[m.model_copy() for m in INITIAL_MINISTERS],
    )
    defaults.update(overrides)
    return GameState(**defaults)


def _minister(state: GameState, name: str) -> Minister:
    return next(m for m in state.ministers if m.name == name)


# ── 硬状态源助手（AC1）─────────────────────────────────

def test_unavailable_actors_removed_and_idle():
    state = make_state()
    # 初始名册含大量未出仕（idle）与已出局（removed）人物
    baseline = set(unavailable_actors(state))
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    _minister(state, "汤和").status = MinisterStatus.IDLE
    actors = unavailable_actors(state)
    assert actors["徐达"] == "已处决/出局"
    assert actors["汤和"] == "已罢免"
    assert "徐达" in roster_names(state)
    assert "徐达" not in active_actor_names(state)
    assert "汤和" not in active_actor_names(state)
    assert set(actors) == baseline | {"徐达", "汤和"}


def test_roster_superset_of_active():
    state = make_state()
    assert active_actor_names(state) <= roster_names(state)
    assert len(active_actor_names(state)) > 0


# ── 校验器：规则A（不可用人物仍在活动）（AC2）───────────

def test_flags_removed_minister_speaking_in_court():
    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    issues = validate_narrative_text("徐达拱手道：主公圣明。", state)
    assert len(issues) == 1
    assert issues[0]["type"] == "unavailable_actor_activity"
    assert issues[0]["actor"] == "徐达"


def test_flags_idle_minister_court_activity():
    state = make_state()
    _minister(state, "汤和").status = MinisterStatus.IDLE
    issues = validate_narrative_text("汤和入朝禀报军情。", state)
    assert len(issues) == 1
    assert issues[0]["actor"] == "汤和"


def test_no_flag_idle_minister_external_action():
    # 语义口径：IDLE（未出仕/被罢免）仅禁"我方朝堂活动"；
    # 外部人物背景行事（韩林儿/陈友谅等率军）是合法史实，不误报。
    state = make_state()
    issues = validate_narrative_text("韩林儿率军北上，声势浩大。", state)
    assert issues == []


def test_flags_removed_minister_colon_prefix():
    state = make_state()
    _minister(state, "常遇春").status = MinisterStatus.REMOVED
    issues = validate_narrative_text("常遇春：臣以为当速战。", state)
    assert len(issues) == 1
    assert issues[0]["actor"] == "常遇春"


def test_no_false_positive_active_minister():
    state = make_state()
    issues = validate_narrative_text("徐达拱手道：主公圣明。", state)
    assert issues == []


def test_no_false_positive_execution_fact_description():
    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    # 叙述处决事实本身合规（被害性动词不在活动谓词表）
    issues = validate_narrative_text("主公下令处决徐达，斩首示众，朝野震动。", state)
    assert issues == []


def test_flags_removed_minister_gongshou_and_xiading():
    # PRD R2 谓词表含 拱手/下令（活动性动词），REMOVED 命中即检出
    state = make_state()
    _minister(state, "常遇春").status = MinisterStatus.REMOVED
    for text in ("常遇春拱手行礼，退于班列。", "常遇春下令增筑城墙。"):
        issues = validate_narrative_text(text, state)
        assert len(issues) == 1, f"{text!r} -> {issues}"
        assert issues[0]["type"] == "unavailable_actor_activity"


def test_no_false_positive_past_tense_description():
    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    issues = validate_narrative_text("徐达生前曾率军北伐，屡建奇功。", state)
    assert issues == []


def test_no_false_positive_past_tense_markers():
    # 过去时标记（生前/当年/曾/曾经）接活动谓词 → 生平叙述，不得误报；
    # 规则A（活动）与规则B（朝堂行事 token）都不误报
    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    for text in (
        "徐达生前率军北伐，屡建奇功。",
        "徐达当年入朝，屡献良策。",
        "徐达曾率军北伐，威震塞北。",
        "徐达曾经主持漕运，官民称颂。",
    ):
        issues = validate_narrative_text(text, state)
        assert issues == [], f"{text!r} -> {issues}"


def test_no_false_positive_group_speech():
    # 群体齐声发言（百官齐声/众将齐声/众人齐道/将士齐呼）是合法叙事，不得误报虚构人物
    state = make_state()
    for text in (
        "百官齐声道：主公英明！",
        "众将齐声道：愿听号令！",
        "众人齐道：臣等附议。",
        "群臣齐声应道：陛下圣明！",
        "将士齐呼：必胜！",
    ):
        issues = validate_narrative_text(text, state)
        assert issues == [], f"{text!r} -> {issues}"


def test_no_false_positive_external_background_mention():
    state = make_state()
    assert "张士诚" in EXTERNAL_ENTITIES
    issues = validate_narrative_text("张士诚据姑苏，陈友谅水师蔽江，元廷坐视。", state)
    assert issues == []


def test_no_false_positive_region_and_titles():
    state = make_state()
    issues = validate_narrative_text("朕下令赈济应天。士卒叩首称谢。", state)
    assert issues == []


# ── 校验器：规则B（虚构人物发言）（AC2）─────────────────

def test_flags_invented_speaker():
    state = make_state()
    issues = validate_narrative_text("赵四海：此事万万不可。", state)
    assert len(issues) == 1
    assert issues[0]["type"] == "invented_speaker"
    assert issues[0]["actor"] == "赵四海"


def test_no_false_positive_common_speaker_prefix():
    state = make_state()
    for sentence in ("传旨太监：圣旨到——", "军前斥候：敌情有变！", "老臣：主公三思。"):
        assert validate_narrative_text(sentence, state) == [], sentence


# ── 净化兜底（AC2/AC3）────────────────────────────────────

def test_sanitize_removes_only_offending_sentences():
    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    text = "徐达拱手道：主公圣明。国库渐盈，民心稍安，军心振奋，四方来贺，朝野同庆。"
    issues = validate_narrative_text(text, state)
    cleaned = sanitize_narrative(text, issues)
    assert "徐达" not in cleaned
    assert "国库渐盈" in cleaned


def test_sanitize_falls_back_when_fully_offending():
    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    text = "徐达拱手道：主公圣明。"
    issues = validate_narrative_text(text, state)
    assert sanitize_narrative(text, issues) == FALLBACK_NARRATIVE


# ── prompt 守卫（AC3）────────────────────────────────────

def test_build_prompt_guard_lists_unavailable():
    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    guard = build_prompt_guard(state)
    assert "徐达" in guard
    assert "不得发言" in guard


def test_build_prompt_guard_only_removed_not_idle():
    # 守卫只列 REMOVED：初始 IDLE（未出仕/史实背景人物）不注入 prompt，避免膨胀与语义冲突
    state = make_state()
    guard = build_prompt_guard(state)
    assert "郭子兴" in guard  # 初始名册唯一 removed
    assert "韩林儿" not in guard
    assert "陈友谅" not in guard


# ── 闭环：校验→重试→净化（AC3）───────────────────────────

class _ScriptedNarrativeProvider:
    """按轮次返回预设叙事；记录收到的 fix_instruction。"""

    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.calls: list[str | None] = []

    async def generate_narrative(self, *args, fix_instruction=None, **kwargs):
        self.calls.append(fix_instruction)
        if len(self.outputs) == 1:
            return self.outputs[0]
        return self.outputs.pop(0)


def _bad_removed_narrative(state) -> str:
    return "徐达拱手道：主公圣明。"


def _run_ensure(state, provider, *, max_retries=1) -> str:
    import asyncio
    return asyncio.run(ensure_narrative_consistent(
        provider, state,
        generate=lambda fix_instruction=None: provider.generate_narrative(fix_instruction=fix_instruction),
        max_retries=max_retries,
    ))


def test_ensure_consistent_ok_single_call():
    state = make_state()
    provider = _ScriptedNarrativeProvider(["国库渐盈，民心稍安。"])
    result = _run_ensure(state, provider)
    assert result == "国库渐盈，民心稍安。"
    assert provider.calls == [None]


def test_ensure_consistent_retry_after_fix():
    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    provider = _ScriptedNarrativeProvider([_bad_removed_narrative(state), "国库渐盈，民心稍安。"])
    result = _run_ensure(state, provider)
    assert result == "国库渐盈，民心稍安。"
    assert len(provider.calls) == 2
    assert "徐达" in (provider.calls[1] or "")


def test_ensure_consistent_sanitizes_when_retry_fails():
    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    provider = _ScriptedNarrativeProvider([_bad_removed_narrative(state), _bad_removed_narrative(state)])
    result = _run_ensure(state, provider)
    assert result == FALLBACK_NARRATIVE
    assert len(provider.calls) == 2


def test_ensure_consistent_max_retries_zero():
    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    provider = _ScriptedNarrativeProvider([_bad_removed_narrative(state)])
    result = _run_ensure(state, provider, max_retries=0)
    assert result == FALLBACK_NARRATIVE
    assert len(provider.calls) == 1


def test_retry_instruction_contains_issue_sentence():
    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    issues = validate_narrative_text(_bad_removed_narrative(state), state)
    instruction = build_retry_instruction(issues)
    assert "重写全文" in instruction
    assert "徐达" in instruction


def test_validation_log_records_actions():
    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    provider = _ScriptedNarrativeProvider([_bad_removed_narrative(state), "国库渐盈。"])
    before = len(validation_log)
    _run_ensure(state, provider)
    actions = [entry["action"] for entry in validation_log[before:]]
    assert actions == ["issues", "retry"]


# ── 轻量路径：sanitize_ai_text（AC5）──────────────────────

def test_sanitize_ai_text_clean_passthrough():
    state = make_state()
    text = "国库渐盈，民心稍安。"
    assert sanitize_ai_text(text, state) == text


def test_sanitize_ai_text_cleans_violation():
    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED
    cleaned = sanitize_ai_text(
        "徐达拱手道：主公圣明。国库渐盈，民心稍安，军心振奋，四方来贺，朝野同庆。", state,
    )
    assert "徐达" not in cleaned
    assert "国库渐盈" in cleaned


# ── freeform 丢弃 effects 同源（AC4）──────────────────────

def test_validate_ai_effects_dropped_out_reports_rejected_entries():
    state = make_state()
    dropped: list = []
    valid = validate_ai_effects(
        {
            "global.national_treasury": 30,
            "minister.不存在大臣.loyalty": 5,
            "region.不存在区域.stability": 10,
            "minister.徐达.loyalty": 5,
        },
        state, dropped_out=dropped,
    )
    assert valid == {"global.national_treasury": 30, "minister.徐达.loyalty": 5}
    assert len(dropped) == 2
    assert all(len(item) == 3 for item in dropped)


def test_process_decree_freeform_reports_dropped_effects():
    state = make_state()
    freeform = FreeformResult(
        effects={
            "global.national_treasury": 30,
            "minister.不存在大臣.loyalty": 5,
        },
        narrative="国库渐盈，朝野称贺。",
        rationale="test",
    )
    dropped: list = []
    process_decree(state, freeform=freeform, dropped_out=dropped)
    assert len(dropped) == 1
    assert dropped[0][0] == "minister.不存在大臣.loyalty"


def test_process_decree_freeform_no_dropped_clean():
    state = make_state()
    freeform = FreeformResult(
        effects={"global.national_treasury": 30},
        narrative="国库渐盈，朝野称贺。",
        rationale="test",
    )
    dropped: list = []
    process_decree(state, freeform=freeform, dropped_out=dropped)
    assert dropped == []


def test_dropped_effect_target_in_narrative_flagged():
    """freeform 叙事描述被丢弃 effects 的目标（不在名册的官员）→ 检出并净化。"""
    from engine.state_consistency import validate_narrative_against_dropped

    dropped = [("minister.赵四海.loyalty", 5, "minister 赵四海 不存在")]
    narrative = "赵四海出任户部尚书，整顿度支。国库渐盈，朝野称贺，四方来朝。"
    issues = validate_narrative_against_dropped(narrative, dropped)
    assert len(issues) == 1
    assert issues[0]["type"] == "dropped_effect_target"
    assert issues[0]["actor"] == "赵四海"
    cleaned = sanitize_narrative(narrative, issues)
    assert "赵四海" not in cleaned
    assert "国库渐盈" in cleaned


def test_dropped_effect_target_no_issue_when_absent():
    from engine.state_consistency import validate_narrative_against_dropped

    dropped = [("minister.赵四海.loyalty", 5, "minister 赵四海 不存在")]
    narrative = "国库渐盈，朝野称贺。"
    assert validate_narrative_against_dropped(narrative, dropped) == []


def test_invented_court_actor_flagged():
    state = make_state()
    issues = validate_narrative_text("赵四海入朝上奏，力陈边患。", state)
    assert any(i["type"] == "invented_court_actor" for i in issues)
    assert issues[0]["actor"] == "赵四海"


def test_no_false_positive_known_actor_court_activity():
    state = make_state()
    # 在朝大臣行朝堂之事 + 外部历史人物背景提及，均不误报
    issues = validate_narrative_text("徐达入朝上奏，力陈边患。张士诚据姑苏。", state)
    assert issues == []


def test_no_false_positive_external_name_tail_token():
    state = make_state()
    # "察罕帖木儿入朝" 的 token 候选"帖木儿"是外部实体尾缀，不误报
    issues = validate_narrative_text("察罕帖木儿率军南下，兵锋直指徐州。", state)
    assert issues == []


# ── 结构化路径集成（AC3，经 _generate_narrative_with_streaming）─

def test_streaming_narrative_sanitized_stored_copy():
    """流式路径：入库副本必须净化（流式文本已推送，残留由 prompt 守卫兜底）。"""
    from api.state import _generate_narrative_with_streaming

    state = make_state()
    _minister(state, "徐达").status = MinisterStatus.REMOVED

    class _StreamProvider:
        async def stream_narrative(self, attribution, game_state, chain_events, decree):
            yield "徐达拱手道：主公圣明。国库渐盈，民心稍安，军心振奋，四方来贺。"

        async def generate_narrative(self, *args, **kwargs):
            return "国库渐盈，民心稍安，军心振奋，四方来贺。"

    streamed: list[str] = []

    async def callback(chunk: str) -> None:
        streamed.append(chunk)

    import asyncio
    result = asyncio.run(_generate_narrative_with_streaming(
        _StreamProvider(), {}, state, [], StructuredDecree(type=DecreeType.TAX_INCREASE), callback,
    ))
    assert "徐达" not in result
    assert "国库渐盈" in result
