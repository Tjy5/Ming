"""D100 骰子检定：roll_d100 / DC 难度修正 / 结果分级。

规则（初版参数，数值平衡归阶段D）：
- 目标值 = 属性半值 + 技能半值修正 + DC 难度修正；无相关技能时按属性半值。
- DC：简易 +20 / 常规 0 / 困难 -20 / 极难 -40。
- 分级：1-5 大成功；≤目标值 成功；>目标值 失败；96-100 大失败。
  大成功/大失败判定优先于目标值比较。
- 骰子支持注入随机源（rng 参数）与全局 seed（测试/回放用）。
"""
from __future__ import annotations

import random

from models.trpg import (
    CharacterSheet,
    RollResult,
    TIER_CRITICAL_FAILURE,
    TIER_CRITICAL_SUCCESS,
    TIER_FAILURE,
    TIER_SUCCESS,
)

# ── 难度修正 ─────────────────────────────────────────────

DC_MODIFIERS: dict[str, int] = {
    "简易": 20,
    "常规": 0,
    "困难": -20,
    "极难": -40,
    # 英文别名（前端/脚本可用）
    "easy": 20,
    "normal": 0,
    "hard": -20,
    "extreme": -40,
}

# 大小成功/失败的固定骰面区间（优先于目标值比较）
CRITICAL_SUCCESS_MAX = 5       # 1-5 大成功
CRITICAL_FAILURE_MIN = 96      # 96-100 大失败

# ── 随机源 ───────────────────────────────────────────────

_default_rng: random.Random | None = None


def set_seed(seed: int | None) -> None:
    """设置全局骰子随机源；seed=None 恢复系统随机（测试/回放用）。"""
    global _default_rng
    _default_rng = random.Random(seed) if seed is not None else None


def roll_d100(rng: random.Random | None = None) -> int:
    """掷 1-100。可注入 rng（含 seed）保证可复现。"""
    source = rng if rng is not None else (_default_rng if _default_rng is not None else random)
    return source.randint(1, 100)


# ── DC 与目标值 ──────────────────────────────────────────

def dc_modifier(difficulty: str = "常规") -> int:
    """难度修正；未知难度按常规(0)处理。"""
    return DC_MODIFIERS.get(str(difficulty or "").strip(), 0)


def compute_target(
    sheet: CharacterSheet,
    attr_name: str,
    skill_name: str | None = None,
    difficulty: str = "常规",
) -> int:
    """计算检定目标值（clamp 到 1-100）。

    无技能：目标值 = 属性半值 + DC；
    有技能（且角色卡上存在）：目标值 = 属性半值 + 技能半值 + DC。
    """
    base = sheet.attr(attr_name) // 2
    skill_value = sheet.skill(skill_name)
    if skill_value is not None:
        base += skill_value // 2
    target = base + dc_modifier(difficulty)
    return max(1, min(100, target))


# ── 结果分级 ─────────────────────────────────────────────

def classify_tier(roll: int, target: int) -> str:
    """分级：大小成功/大失败优先于目标值比较。"""
    if roll <= CRITICAL_SUCCESS_MAX:
        return TIER_CRITICAL_SUCCESS
    if roll >= CRITICAL_FAILURE_MIN:
        return TIER_CRITICAL_FAILURE
    return TIER_SUCCESS if roll <= target else TIER_FAILURE


# ── 完整检定 ─────────────────────────────────────────────

def perform_check(
    sheet: CharacterSheet,
    attr_name: str,
    skill_name: str | None = None,
    difficulty: str = "常规",
    rng: random.Random | None = None,
) -> RollResult:
    """执行一次 D100 检定并返回分级结果。"""
    roll = roll_d100(rng)
    target = compute_target(sheet, attr_name, skill_name, difficulty)
    return RollResult(
        roll=roll,
        target=target,
        tier=classify_tier(roll, target),
        dc=dc_modifier(difficulty),
        attr_name=attr_name,
        skill_name=skill_name,
    )
