"""政令执行损耗模型（08-07-decree-execution-loss）。

官僚系统层层传达，政令效果只受实际执行者的可追溯状态影响：

    实际 delta = 目标效果 × executor_factor

设计约束（见 design.md）：
- 未指定实际执行者时不虚构官僚平均值，factor=1。
- 普通行动不生成偏差或暗骰；公开高不确定 roll 由 engine.rng 单独拥有。
- 三路（structured / freeform / trpg writeback）统一调用 apply_execution_loss。
"""

from __future__ import annotations

import math
import random
from typing import Mapping

from engine.execution import legacy_minister_efficiency
from engine.rng import stable_seed
from models.game import GameState

# 损耗系数下界，防止政令完全归零（避免游戏卡死）
MIN_LOSS_FACTOR = 0.05
# 普通行动不允许隐藏偏差。常量保留为兼容读取，但固定为零。
DEVIATION_RATIO = 0.0


def execution_loss_factor(
    state: GameState,
    executor_name: str | None = None,
    *,
    action_kind: str | None = None,
) -> float:
    """Return the deterministic factor for the named actual executor only."""

    if executor_name is None:
        return 1.0
    minister = next((item for item in state.ministers if item.name == executor_name), None)
    if minister is None:
        return 0.0
    _, efficiency = legacy_minister_efficiency(minister, action_kind)
    return float(efficiency)


def seeded_deviation(seed: int | None, magnitude: int) -> int:
    """Compatibility helper for explicit tests; ordinary actions never call it.

    Public gameplay rolls use :mod:`engine.rng` and are persisted as RollRecord.
    """
    if seed is None or magnitude <= 0:
        return 0
    rng = random.Random(seed)
    return rng.randint(-magnitude, magnitude)


def _derive_seed(state: GameState, key: str) -> int | None:
    """确定性 seed 来源。

    仅当 state.execution_rng_seed 被显式设置（运行时）才产生偏差；
    默认 None → 零偏差，保持 PBT/测试确定性。
    """
    base = getattr(state, "execution_rng_seed", None)
    if base is None:
        return None
    return stable_seed("legacy-execution-seed", int(base), key)


def apply_execution_loss(
    state: GameState,
    field_deltas: Mapping[str, int | float],
    seed_keys: Mapping[str, str] | None = None,
    *,
    executor_name: str | None = None,
    action_kind: str | None = None,
) -> dict[str, int | float]:
    """Apply deterministic actual-executor loss with no random deviation.

    返回损耗后的净 delta 字典。三路（structured/freeform/trpg writeback）
    均调用此函数，确保 AI 自由政令无法绕过损耗。

    field_deltas: 已含玩家角色卡修正后的"目标效果"（structured 路由由调用方先算 scale）。
    ``seed_keys`` is accepted only for source compatibility and is ignored.
    """
    del seed_keys
    loss_factor = execution_loss_factor(
        state,
        executor_name,
        action_kind=action_kind,
    )
    result: dict[str, int | float] = {}
    for field, delta in field_deltas.items():
        if delta == 0:
            result[field] = 0
            continue
        scaled = delta * loss_factor
        if isinstance(delta, int):
            result[field] = math.floor(scaled) if scaled > 0 else math.ceil(scaled)
        else:
            result[field] = round(scaled, 2)
    return result
