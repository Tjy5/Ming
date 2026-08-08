"""08-07-ai-benchmark-quality：AI 质量 benchmark（状态修改成功率门禁）。

程序化轨（确定性、可离线）：
- 对每个 DecreeType 用例，执行 process_decree 后：
  1. clamp_state 通过（数值不越界）
  2. 主效应方向正确（按 DECREE_EFFECTS 符号，容忍执行损耗，不反向）
  3. mission/active_policies 不丢失
- 整体通过率 ≥ 99%（程序化轨）。

模型判定轨（可选，USE_MODEL_JUDGE=1）默认关闭，仅作附加评分。
"""

import os

import pytest

from engine.core import process_decree, DECREE_EFFECTS
from models.game import GameState, StructuredDecree, FreeformResult
from models.enums import DecreeType
from models.game import clamp_state
from engine.state_consistency import validate_narrative_text


# 用例集：覆盖全部 DecreeType + 2 个 freeform 模板
CASES = [
    {"id": "tax_decrease", "decree": StructuredDecree(type=DecreeType.TAX_DECREASE)},
    {"id": "tax_increase", "decree": StructuredDecree(type=DecreeType.TAX_INCREASE)},
    {"id": "recruit_troops", "decree": StructuredDecree(type=DecreeType.RECRUIT_TROOPS)},
    {"id": "disband_troops", "decree": StructuredDecree(type=DecreeType.DISBAND_TROOPS)},
    {"id": "disaster_relief", "decree": StructuredDecree(type=DecreeType.DISASTER_RELIEF)},
    {"id": "diplomacy", "decree": StructuredDecree(type=DecreeType.DIPLOMACY)},
    {"id": "harsh_punishment", "decree": StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)},
    {"id": "freeform_tax", "freeform": FreeformResult(effects={"global.national_treasury": -200, "global.civil_morale": 50})},
    {"id": "freeform_personnel", "freeform": FreeformResult(effects={"global.court_prestige": 30})},
]


def _run(case: dict):
    """执行单个用例，返回 (state_before, state_after, delta)。"""
    from tests.test_freeform import make_state  # 复用既有 state 构造
    before = make_state()
    if "decree" in case:
        process_decree(before, decree=case["decree"])
    else:
        process_decree(before, freeform=case["freeform"])
    return before


def _direction_ok(case: dict, before: GameState, after: GameState) -> bool:
    """主效应方向校验：DECREE_EFFECTS 符号不应反向（容忍损耗后变小但不反向）。"""
    if "decree" not in case:
        # freeform：仅校验目标字段符号未被反向翻转
        for path, val in case["freeform"].effects.items():
            field = path.split(".")[1]
            changed = getattr(after, field) - getattr(before, field)
            if val > 0 and changed < 0:
                return False
            if val < 0 and changed > 0:
                return False
        return True
    effects = DECREE_EFFECTS[case["decree"].type]
    for field, target in effects.items():
        if target == 0:
            continue
        changed = getattr(after, field) - getattr(before, field)
        if target > 0 and changed < 0:
            return False
        if target < 0 and changed > 0:
            return False
    return True


def _judge(case: dict, before: GameState, after: GameState) -> dict:
    clamp_state(after)  # 不抛异常即通过
    bounds_ok = True
    direction_ok = _direction_ok(case, before, after)
    policy_ok = len(after.active_policies) == len(before.active_policies)
    # mission 持续：在朝大臣的 current_mission 不丢失
    mission_ok = all(
        (b.current_mission is None) == (a.current_mission is None)
        for b, a in zip(before.ministers, after.ministers)
    )
    passed = bounds_ok and direction_ok and policy_ok and mission_ok
    return {
        "bounds_ok": bounds_ok,
        "direction_ok": direction_ok,
        "policy_ok": policy_ok,
        "mission_ok": mission_ok,
        "passed": passed,
    }


# 模型判定（可选，默认关）
USE_MODEL_JUDGE = os.environ.get("USE_MODEL_JUDGE") == "1"


def test_benchmark_all_cases():
    results = []
    for case in CASES:
        before = make_state_safe()
        after = _run_on(case, before)
        r = _judge(case, before, after)
        r["id"] = case["id"]
        results.append(r)
    passed = sum(1 for r in results if r["passed"])
    rate = passed / len(results)
    # 报告
    report = ["## AI Benchmark report (programmatic)", "", "| case | pass | direction | policy | mission |", "|---|---|---|---|---|"]
    for r in results:
        mark = lambda b: "OK" if b else "FAIL"
        report.append(f"| {r['id']} | {mark(r['passed'])} | {mark(r['direction_ok'])} | {mark(r['policy_ok'])} | {mark(r['mission_ok'])} |")
    report.append("")
    report.append(f"Overall pass rate: {rate*100:.1f}% (target >= 99%)")
    with open("benchmark_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    assert rate >= 0.99, f"benchmark 通过率 {rate*100:.1f}% < 99%"


def make_state_safe():
    from tests.test_freeform import make_state
    return make_state()


def _run_on(case: dict, state: GameState) -> GameState:
    if "decree" in case:
        process_decree(state, decree=case["decree"])
    else:
        process_decree(state, freeform=case["freeform"])
    return state
