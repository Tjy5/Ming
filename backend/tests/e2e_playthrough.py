"""e2e：脚本化玩家走史实主路径（1328 出生 → 1368 建明），ACD1/ACD5 核验手段。

- 标记 @pytest.mark.e2e；默认跳过（pytest 7.4 的 addopts -m 会覆盖命令行 -m，
  故用环境变量闸口）：`RUN_E2E=1 python -m pytest tests -m e2e` 运行通关模拟；
  常规套件命令 `python -m pytest tests -q -m "not e2e"`。
- 无外部依赖、可复现：测试注入 tests.fakes.FakeProvider（确定性规则/模板，
  产品无内置 provider）；dice.set_seed 固定骰序；
  治理段用 engine 层（process_decree/advance_month/check_game_end）驱动，
  跑团段走 API 层（/act、/milestones/{id}/complete）。
- 断言（design 第 5 节）：
  * 开局 1328-10/天历元年/childhood/life_story；
  * 跑团段：里程碑顺序完成、时间对齐里程碑日期、yingtian-founding 恰好切换一次
    phase → governance、角色卡状态连续；
  * 治理段：月推进 1356-03 → 1368-01，穿插辅助检定（每约 2 月 1 次）；
  * 终局：ming-proclamation 已达成 + 建明结局（check_game_end victory）+
    1368 时**主修属性**（政治或军事二选一，主修方向玩家自选）在 [75, 90]；
    硬断言不放宽——本 e2e 的玩家策略为全投军事（每次检定 attr=军事）。
"""
import asyncio
import os

import pytest

from ai.provider import ResilientProvider
from fakes import FakeProvider
from api import state as api_state
from api import trpg as trpg_routes
from engine.core import (
    advance_month,
    check_game_end,
    check_preconditions,
    process_decree,
    validate_target,
)
from models.enums import DecreeType, RegionControl, RegionThreat
from models.game import GameState, StructuredDecree, create_initial_state
from models.trpg import PLAYER_NAME, ActRequest
from trpg import character as character_mod
from trpg import dice as dice_mod

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.getenv("RUN_E2E") != "1",
        reason="e2e 通关模拟：设 RUN_E2E=1 运行（常规套件默认跳过）",
    ),
]

# 治理段辅助检定：显式"简易"（成长强度按步骤 6/平衡修复测算——早期每月 1 次
# 快速积累，之后每 2 月 1 次维持；总量约 100 次 ≈ 140 技能点 → 主属性 75-90；
# 以 1368 硬断言复验，实测落点不足时微调此节奏）
GOV_ACT_MONTHLY_BURST_MONTHS = 60
GOV_ACT_EVERY_N_MONTHS = 2
# 治理政令策略的派系目标轮换
DIPLOMACY_TARGETS = ["龙凤政权", "汉政权", "吴政权", "元廷", "东南群雄"]

# 史实主路径跑团段：里程碑 + 完成后的期望状态。
# 章末里程碑：advance_chapter 先跳到下一章 start_year，时间回拨守卫（步骤 3
# 收尾裁决）拒绝回退到里程碑日期 → 期望时间为下一章起点（wandering/cross-yangtze）。
MAIN_PATH_MILESTONES: list[tuple[str, str, int, int]] = [
    # (milestone_id, 期望章, 期望年, 期望月)
    ("birth-1328", "childhood", 1328, 10),
    ("famine-1344", "monk_wanderer", 1344, 4),
    ("wandering-1345", "enlistment", 1352, 1),   # 僧旅章末 → 跳投军章起点，不回拨
    ("enlist-1352", "enlistment", 1352, 3),
    ("recruit-1353", "enlistment", 1353, 6),
    ("cross-yangtze-1355", "warlord", 1356, 1),  # 投军章末 → 跳割据章起点，不回拨
    ("yingtian-founding", "warlord", 1356, 3),
]


def _fake_provider():
    return ResilientProvider(FakeProvider(), timeout=1, retries=1)


def _can_issue(state: GameState, decree: StructuredDecree) -> bool:
    return (
        check_preconditions(state, decree) is None
        and validate_target(decree, state) is None
    )


def _pick_decrees(state: GameState, month_idx: int) -> list[StructuredDecree]:
    """每月至多 3 道（domestic + military + diplomacy 各一）的稳健施政策略。"""
    decrees: list[StructuredDecree] = []

    worst = min(state.regions, key=lambda r: r.stability)
    if worst.stability < 55:
        d = StructuredDecree(type=DecreeType.DISASTER_RELIEF, target=worst.name)
        if _can_issue(state, d):
            decrees.append(d)
    elif state.national_treasury < 40:
        d = StructuredDecree(type=DecreeType.TAX_INCREASE)
        if _can_issue(state, d):
            decrees.append(d)
    elif state.court_prestige < 70:
        d = StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)
        if _can_issue(state, d):
            decrees.append(d)

    threatened_low = [r for r in state.regions if r.threat != RegionThreat.NONE and r.stability < 65]
    if threatened_low and state.military_strength < 140:
        d = StructuredDecree(type=DecreeType.RECRUIT_TROOPS)
        if _can_issue(state, d):
            decrees.append(d)

    d = StructuredDecree(type=DecreeType.DIPLOMACY, target=DIPLOMACY_TARGETS[month_idx % len(DIPLOMACY_TARGETS)])
    if _can_issue(state, d):
        decrees.append(d)

    return decrees


def _resolve_script_events(state: GameState) -> None:
    """解决全部脚本事件（史实主路径：均选第一个 choice，含阻塞与非阻塞）。"""
    from engine.core import clamp_state
    from models.enums import RegionControl, RegionThreat
    for evt in list(state.active_events):
        if not evt.is_scripted:
            continue
        if evt.choices:
            choice = evt.choices[0]
            for path, value in choice.state_effects.items():
                parts = path.split(".")
                if parts[0] == "global" and len(parts) == 2 and hasattr(state, parts[1]):
                    setattr(state, parts[1], getattr(state, parts[1]) + value)
                elif parts[0] == "region" and len(parts) == 3:
                    for r in state.regions:
                        if r.name == parts[1] and hasattr(r, parts[2]):
                            if parts[2] in ("threat", "control"):
                                # 史实威胁清除：str → 枚举（不可逆）
                                enum_cls = RegionThreat if parts[2] == "threat" else RegionControl
                                try:
                                    setattr(r, parts[2], enum_cls(str(value)))
                                except ValueError:
                                    pass
                            else:
                                setattr(r, parts[2], getattr(r, parts[2]) + value)
                            break
                elif parts[0] == "faction" and len(parts) == 3:
                    for f in state.factions:
                        if f.name == parts[1] and hasattr(f, parts[2]):
                            setattr(f, parts[2], getattr(f, parts[2]) + value)
                            break
            for item in choice.loyalty_effects:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    for m in state.ministers:
                        if m.name == item[0]:
                            m.loyalty = max(0, min(100, m.loyalty + item[1]))
                            break
        state.active_events = [e for e in state.active_events if e is not evt]
        if evt.script_id:
            state.resolved_script_ids.add(evt.script_id)
        clamp_state(state)


@pytest.mark.e2e
def test_historical_main_path_playthrough():
    dice_mod.set_seed(2026)
    api_state._provider = _fake_provider()
    state = create_initial_state()
    character_mod.ensure_sheets(state)
    api_state._state = state
    sheet = state.character_sheets[PLAYER_NAME]

    # ── 1. 新档开局 ──
    assert state.time.year == 1328
    assert state.time.month == 10
    assert state.time.era_name == "天历"
    assert state.time.era_year == 1
    assert state.chapter == "childhood"
    assert state.phase == "life_story"

    # ── 2. 跑团段：里程碑顺序完成 + 每章穿插辅助检定 ──
    phase_switch_count = 0
    for idx, (milestone_id, expected_chapter, expected_year, expected_month) in enumerate(MAIN_PATH_MILESTONES):
        # 章内穿插 1-2 次辅助检定（规则回退；早期章默认难度本就轻松）
        resp = asyncio.run(trpg_routes.act(ActRequest(
            action_text="操练兵马，亲授阵法", attr="军事",
        )))
        assert resp["option_id"] is None  # 未传 option_id → 回显 null
        state = api_state._state
        sheet = state.character_sheets[PLAYER_NAME]

        resp = asyncio.run(trpg_routes.complete_milestone(milestone_id))
        state = api_state._state
        assert resp["milestone"] == milestone_id
        # 时间对齐里程碑日期（仅向前）
        assert state.time.year == expected_year, f"{milestone_id} 年份对齐失败: {state.time.year}"
        assert state.time.month == expected_month, f"{milestone_id} 月份对齐失败: {state.time.month}"
        if milestone_id == "yingtian-founding":
            assert resp["phase"] == "governance"
            phase_switch_count += 1
        else:
            assert resp["phase"] == "life_story"
        assert state.chapter == expected_chapter, f"{milestone_id} 章推进失败: {state.chapter}"
        assert state.phase == ("governance" if milestone_id == "yingtian-founding" else "life_story")

    # phase 恰好切换一次
    assert phase_switch_count == 1

    # 角色卡状态连续：切换只改 phase/time，属性/特质/成长记录保留
    assert state.time.year == 1356
    assert state.time.month == 3
    assert state.time.era_name == "至正"
    assert state.time.era_year == 16
    assert sheet.attrs["军事"] >= 50
    assert "坚韧" in sheet.traits
    assert any("关键事件" in e.source for e in state.growth_log)

    # ── 3. 治理段：月推进 + 辅助检定 + 稳健施政 ──
    acts = 0
    month_idx = 0
    early_game_over = None
    while not (state.time.year == 1368 and state.time.month >= 1) and state.time.year <= 1368:
        game_over = check_game_end(state)
        if game_over:
            early_game_over = game_over
            break
        month_idx += 1
        for decree in _pick_decrees(state, month_idx):
            process_decree(state, decree=decree)
        _resolve_script_events(state)
        if month_idx <= GOV_ACT_MONTHLY_BURST_MONTHS or month_idx % GOV_ACT_EVERY_N_MONTHS == 0:
            api_state._state = state
            asyncio.run(trpg_routes.act(ActRequest(
                action_text="操练兵马，亲授阵法", attr="军事", difficulty="简易",
            )))
            state = api_state._state
            sheet = state.character_sheets[PLAYER_NAME]
            acts += 1
        advance_month(state)
        if state.time.year > 1368:
            break
    state = api_state._state
    sheet = state.character_sheets[PLAYER_NAME]

    # ── 4. 完成 ming-proclamation（1368-01 建明）──
    assert "ming-proclamation" not in state.resolved_script_ids
    if early_game_over is None:
        resp = asyncio.run(trpg_routes.complete_milestone("ming-proclamation"))
        state = api_state._state
        assert resp["milestone"] == "ming-proclamation"
        assert "ming-proclamation" in state.resolved_script_ids
    game_over = check_game_end(state)

    # ── 5. 终局断言（硬断言，不放宽）──
    fallen = sum(1 for r in state.regions if r.control == RegionControl.FALLEN)
    unstable = sum(1 for r in state.regions if r.control == RegionControl.UNSTABLE)
    # 建明结局达成
    assert game_over is not None, (
        f"未到达终局判定：{state.time.year}-{state.time.month} "
        f"early_game_over={early_game_over} 沦陷={fallen} 失控={unstable} "
        f"威望={state.court_prestige} 叛乱={[f.rebellion_risk for f in state.factions]}"
    )
    assert game_over["result"] == "victory", (
        f"结局非胜利：{game_over} @ {state.time.year}-{state.time.month} "
        f"沦陷={fallen} 失控={unstable} 威望={state.court_prestige} "
        f"叛乱={[f.rebellion_risk for f in state.factions]} "
        f"军事={sheet.attrs['军事']} 政治={sheet.attrs['政治']} 辅助检定={acts}"
    )
    # 1368 主修属性在 [75, 90]（裁决口径 a：政治/军事二选一，主修方向玩家自选；
    # 本 e2e 全投军事——每次辅助检定 attr=军事，or 的另一侧覆盖纯政治主修玩家）
    military, political = sheet.attrs["军事"], sheet.attrs["政治"]
    assert 75 <= military <= 90 or 75 <= political <= 90, (
        f"主修属性未达 75-90：军事={military} 政治={political} "
        f"辅助检定次数={acts} 时间={state.time.year}-{state.time.month}"
    )
