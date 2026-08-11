from __future__ import annotations

import pytest

from ai.narrative_context import NarrativeActivityView, build_narrative_context
from ai.narrative_validators import facts_narrative, validate_narrative_candidate
from api.action_service import ActionService
from db import saves, worlds
from engine.core import check_game_end
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, PlayerWorldDelta
from models.world import (
    Duration,
    PlayerWorldStatus,
    WorldInstant,
    new_activity_id,
    new_checkpoint_id,
    new_client_action_id,
    new_delta_id,
)
from models.world_state import ExecutorFacts, RollRecord, VisibleRollModifier


def _committed_context(monkeypatch, tmp_path, *, player_update=None):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "narrative-validators.db")
    saves.init_db()
    initial = create_initial_state()
    if player_update:
        initial.player_world_status = initial.player_world_status.model_copy(
            update=player_update,
        )
    root = worlds.create_game_with_root(initial)
    parent = worlds.load_version(root.version_id).state
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="继续当前世界",
        action_kind="decree",
    )
    proposal = AdjudicationProposal(
        result_tier="success",
        key_factors=["当前事实允许行动"],
        immediate_changes=["世界继续演化"],
        execution_status="completed",
    )
    result = worlds.commit_settlement(intent, parent, proposal)
    state = worlds.load_version(result.version.version_id).state
    context = build_narrative_context(
        path_id="structured_action",
        state=state,
        settlement=result.facts,
        action_text=intent.raw_text,
    )
    return state, context


def _terminal_context(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "terminal-narrative.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="孤身守住断桥掩护全军撤退",
        action_kind="warfare",
    )
    factors = ["主角独自留守断桥", "敌军已经完成合围"]
    proposal = AdjudicationProposal(
        result_tier="failure",
        key_factors=factors,
        immediate_changes=["主角死亡，当前世界线终止"],
        execution_status="failed",
        duration_candidate=Duration(unit="hour", value=2),
        duration_reason="断桥阻击持续两小时",
        deltas=[
            PlayerWorldDelta(
                delta_id=new_delta_id(),
                operation="death",
                before_value="alive",
                value="dead",
                trigger_action=intent.client_action_id,
                direct_cause="断桥失守后被合围的敌军杀死",
                key_factors=factors,
                causal_summary="主角独自断后且退路被切断，最终在合围中死亡",
            ),
        ],
    )

    class _Adjudicator:
        async def adjudicate(self, _intent, _state):
            return proposal

    execution = ActionService(adjudicator=_Adjudicator()).execute_sync(intent)
    context = build_narrative_context(
        path_id="structured_action",
        state=execution.state,
        settlement=execution.result.facts,
        action_text=intent.raw_text,
    )
    return execution.state, context


def _codes(text, *, state, context):
    return {
        finding.code
        for finding in validate_narrative_candidate(
            text,
            context=context,
            state=state,
        )
    }


def _context_with_roll(context):
    roll = RollRecord(
        roll_id="a" * 64,
        protocol_version="d100-v1",
        raw_d100=42,
        target_value=55,
        result_tier="success",
        modifiers=[
            VisibleRollModifier(name="士气", value=5, source_fact="军心稳定"),
        ],
        uncertainty_reasons=["opposition"],
        fact_references=["metric:military_morale"],
        checkpoint_slot="action",
    )
    facts = context.settlement.model_copy(update={"rolls": [roll]})
    return context.model_copy(update={"settlement": facts, "rolls": [roll]})


def test_settlement_result_factors_and_changes_reject_uncommitted_claims(
    monkeypatch,
    tmp_path,
):
    state, context = _committed_context(monkeypatch, tmp_path)

    codes = _codes(
        "行动失败。关键依据：虚构依据。已生效变化：国库归零。",
        state=state,
        context=context,
    )

    assert {
        "settlement_result_tier_mismatch",
        "uncommitted_key_factor",
        "uncommitted_immediate_change",
    } <= codes


def test_executor_rejection_and_dynamic_actor_follow_committed_attribution(
    monkeypatch,
    tmp_path,
):
    state, context = _committed_context(monkeypatch, tmp_path)
    people = [
        entity.model_copy(update={"status": "active", "available": True})
        for entity in context.entities
        if entity.entity_type == "person"
    ]
    assert len(people) >= 2
    requested, actual = people[:2]
    executor = ExecutorFacts(
        requested_executor_id=requested.entity_id,
        actual_executor_id=actual.entity_id,
        selection_source="player",
        execution_status="completed",
        entity_type=actual.entity_type,
        display_name=actual.display_name,
        version_id=context.version_id,
    )
    attribution = context.settlement.attribution.model_copy(update={
        "requested_executor_id": requested.entity_id,
        "actual_executor_id": actual.entity_id,
        "execution_status": "completed",
        "executor_facts": executor,
    })
    facts = context.settlement.model_copy(update={"attribution": attribution})
    context = context.model_copy(update={
        "entities": people,
        "executor": executor,
        "settlement": facts,
    })

    labeled_codes = _codes(
        f"实际执行者：{requested.display_name}。执行状态：blocked。",
        state=state,
        context=context,
    )
    actor_codes = _codes(
        f"{requested.display_name}奉命率军执行。",
        state=state,
        context=context,
    )

    assert "actual_executor_mismatch" in labeled_codes
    assert "execution_status_mismatch" in labeled_codes
    assert "unauthorized_executor_claim" in actor_codes


def test_roll_raw_target_modifier_and_tier_are_bound_to_one_committed_roll(
    monkeypatch,
    tmp_path,
):
    state, context = _committed_context(monkeypatch, tmp_path)
    context = _context_with_roll(context)

    codes = _codes(
        "公开检定：D100骰点77，目标值60，修正为天候-10，结果critical_failure。",
        state=state,
        context=context,
    )

    assert {
        "roll_raw_mismatch",
        "roll_target_mismatch",
        "roll_modifier_mismatch",
        "roll_result_tier_mismatch",
    } <= codes


def test_uncommitted_luck_and_reroll_claims_are_rejected(monkeypatch, tmp_path):
    state, context = _committed_context(monkeypatch, tmp_path)

    assert "uncommitted_roll" in _codes(
        "行动全凭运气侥幸成功。",
        state=state,
        context=context,
    )

    context = _context_with_roll(context)
    codes = _codes(
        "公开检定先以D100骰点42判定，随后重掷D100骰点77。",
        state=state,
        context=context,
    )
    assert "uncommitted_reroll" in codes
    assert "roll_raw_mismatch" in codes


def test_base_and_effective_band_claims_match_current_projection(monkeypatch, tmp_path):
    state, context = _committed_context(monkeypatch, tmp_path)
    metric = next(
        item
        for item in context.world_state.metrics
        if item.base_band is not None and item.effective_band is not None
    )
    key = metric.target.metric_key

    assert "numeric_band_mismatch" in _codes(
        f"{key}基础档位为虚构，{key}有效档位为虚构。",
        state=state,
        context=context,
    )
    assert "numeric_band_mismatch" not in _codes(
        f"{key}基础档位为{metric.base_band}，{key}有效档位为{metric.effective_band}。",
        state=state,
        context=context,
    )


def test_activity_checkpoint_remaining_time_and_calendar_reject_stale_claims(
    monkeypatch,
    tmp_path,
):
    state, context = _committed_context(monkeypatch, tmp_path)
    activity = NarrativeActivityView(
        activity_id=new_activity_id(),
        status="in_progress",
        intent="修筑堤坝",
        started_at=WorldInstant(absolute_hour=context.time.absolute_hour),
        planned_duration=Duration(unit="hour", value=100),
        elapsed_hours=24,
        remaining_hours=76,
        checkpoint_id=new_checkpoint_id(),
        checkpoint_sequence=2,
    )
    context = context.model_copy(update={"current_activity": activity})
    calendar = context.time.calendar
    wrong_month = calendar.month % 12 + 1
    wrong_day = calendar.day % 28 + 1

    activity_codes = _codes(
        "当前活动状态：completed；检查点序号9；已用时99小时；剩余时长0小时；"
        "活动中断依据：虚构桥断；修筑堤坝已经完成。",
        state=state,
        context=context,
    )
    time_codes = _codes(
        f"当前为{calendar.year}年{wrong_month}月{wrong_day}日。",
        state=state,
        context=context,
    )

    assert {
        "activity_status_mismatch",
        "activity_checkpoint_mismatch",
        "activity_elapsed_time_mismatch",
        "activity_remaining_time_mismatch",
        "activity_interruption_mismatch",
        "future_activity_completion",
    } <= activity_codes
    assert "current_time_mismatch" in time_codes


def test_dead_player_cannot_be_resurrected_or_continue_without_committed_facts(
    monkeypatch,
    tmp_path,
):
    state, context = _committed_context(monkeypatch, tmp_path)
    context = context.model_copy(update={
        "player": context.player.model_copy(update={"life_status": "dead"}),
    })

    codes = _codes(
        "主角死而复生，主角继续行动。",
        state=state,
        context=context,
    )

    assert "dead_player_continuation" in codes


def test_alive_player_rejects_indirect_death_and_terminal_wording(monkeypatch, tmp_path):
    state, context = _committed_context(monkeypatch, tmp_path)

    codes = _codes(
        "主角拒不归降，最终困毙山野、身先殒没，此局已终。",
        state=state,
        context=context,
    )

    assert "uncommitted_player_death" in codes


def test_legacy_player_status_defaults_to_governing_without_terminal_ids():
    status = PlayerWorldStatus.model_validate(
        {
            "life_status": "alive",
            "freedom_status": "free",
            "identity_summary": "旧存档主角",
        },
    )

    assert status.regime_status == "governing"
    assert status.terminal_settlement_id is None
    assert status.terminal_version_id is None


@pytest.mark.parametrize(
    ("label", "regime_status", "freedom_status"),
    [
        ("执政", "governing", "free"),
        ("失势", "overthrown", "free"),
        ("被俘", "overthrown", "detained"),
        ("流亡", "overthrown", "exiled"),
        ("政权覆灭", "regime_destroyed", "free"),
    ],
)
def test_non_death_player_regime_and_freedom_states_remain_actionable(
    monkeypatch,
    tmp_path,
    label,
    regime_status,
    freedom_status,
):
    state, context = _committed_context(
        monkeypatch,
        tmp_path,
        player_update={
            "regime_status": regime_status,
            "freedom_status": freedom_status,
            "identity_summary": label,
            "actionable_goal_ids": [f"recover-from-{label}"],
        },
    )

    assert context.player.life_status == "alive"
    assert context.player.regime_status == regime_status
    assert context.player.freedom_status == freedom_status
    assert context.player.actionable_goal_ids == [f"recover-from-{label}"]
    assert check_game_end(state) is None
    assert _codes(
        f"主角当前处于{label}处境，但仍可继续行动并寻找翻身机会。",
        state=state,
        context=context,
    ) == set()


def test_committed_death_fallback_uses_exact_cause_and_rejects_invented_cause(
    monkeypatch,
    tmp_path,
):
    state, context = _terminal_context(monkeypatch, tmp_path)

    fallback = facts_narrative(context)
    assert "直接死因：断桥失守后被合围的敌军杀死" in fallback
    assert "因果摘要：主角独自断后且退路被切断，最终在合围中死亡" in fallback
    assert "当前世界线在此终止" in fallback
    assert _codes(fallback, state=state, context=context) == set()

    invented = _codes(
        "主角死亡。直接死因：不存在的宫廷毒杀。由继承人继续下一回合。",
        state=state,
        context=context,
    )
    assert "player_death_cause_mismatch" in invented
    assert "player_death_cause_missing" in invented
    assert "dead_player_continuation" in invented

    omitted = _codes(
        "行动已经结算，局势暂时平静。",
        state=state,
        context=context,
    )
    assert {
        "committed_player_death_omitted",
        "player_death_cause_missing",
    } <= omitted


def test_facts_fallback_carries_current_activity_checkpoint_and_interruptions(
    monkeypatch,
    tmp_path,
):
    state, context = _committed_context(monkeypatch, tmp_path)
    facts = context.settlement.model_copy(update={"crossed_events": ["道路中断"]})
    activity = NarrativeActivityView(
        activity_id=new_activity_id(),
        status="awaiting_player_decision",
        intent="转运粮草",
        started_at=WorldInstant(absolute_hour=context.time.absolute_hour),
        planned_duration=Duration(unit="hour", value=120),
        elapsed_hours=48,
        remaining_hours=72,
        checkpoint_id=new_checkpoint_id(),
        checkpoint_sequence=3,
        crossed_events=["道路中断"],
        interruption_facts=["桥梁冲毁"],
    )
    context = context.model_copy(update={
        "settlement": facts,
        "current_activity": activity,
    })

    fallback = facts_narrative(context)

    assert "当前活动状态：awaiting_player_decision" in fallback
    assert "检查点序号：3" in fallback
    assert "已用时：48小时" in fallback
    assert "剩余时长：72小时" in fallback
    assert "跨越事件：道路中断" in fallback
    assert "活动中断依据：桥梁冲毁" in fallback
    assert _codes(fallback, state=state, context=context) == set()


def test_labeled_facts_fallback_revalidates_against_roll_and_settlement(
    monkeypatch,
    tmp_path,
):
    state, context = _committed_context(monkeypatch, tmp_path)
    context = _context_with_roll(context)
    fallback = facts_narrative(context)

    assert _codes(fallback, state=state, context=context) == set()
