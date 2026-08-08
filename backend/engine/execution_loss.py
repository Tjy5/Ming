"""政令执行损耗模型（08-07-decree-execution-loss）。

官僚系统层层传达，政令效果受官员腐败度/忠诚/行政能力影响产生损耗，
并叠加可控随机偏差：

    实际 delta = 目标效果 × loss_factor + deviation

设计约束（见 design.md）：
- loss_factor ∈ (0, 1]，纯确定性规则。
- deviation 必须经显式 seed 派生，禁止裸 random/secrets，保证可复现。
- 三路（structured / freeform / trpg writeback）统一调用 apply_execution_loss。
"""

from __future__ import annotations

import math
import random
from typing import Mapping

from models.game import GameState, Minister, MinisterStatus

# 损耗系数下界，防止政令完全归零（避免游戏卡死）
MIN_LOSS_FACTOR = 0.05
# 偏差幅度相对目标效果的比例上限
DEVIATION_RATIO = 0.1


def _active_ministers(state: GameState) -> list[Minister]:
    return [m for m in state.ministers if m.status == MinisterStatus.ACTIVE]


def execution_loss_factor(state: GameState) -> float:
    """全体在任官员均值决定损耗系数。

    腐败↑ / 忠诚↓ / 行政能力↓ → 系数↓（到手越少）。
    廉洁(0)+忠诚(100)+行政(100) → 1.0（零损耗）。
    """
    ministers = _active_ministers(state)
    if not ministers:
        return 1.0
    total = 0.0
    for m in ministers:
        civil = max(0, min(100, m.abilities.civil))
        # 单项效能：反腐(0~1) × 忠诚(0~1) × 行政(0.5~1.0)
        eff = ((100 - m.corruption) / 100.0) * (m.loyalty / 100.0) * (0.5 + civil / 200.0)
        total += eff
    avg = total / len(ministers)
    return max(MIN_LOSS_FACTOR, min(1.0, avg))


def seeded_deviation(seed: int | None, magnitude: int) -> int:
    """可控随机偏差，范围 [-mag, +mag]。

    seed 为 None 时退化为 0（确定性，兼容 PBT）。
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
    return (int(base) ^ hash(key)) & 0xFFFFFFFF


def apply_execution_loss(
    state: GameState,
    field_deltas: Mapping[str, int],
    seed_keys: Mapping[str, str] | None = None,
) -> dict[str, int]:
    """统一损耗入口：对 {field: 目标delta} 施加减损耗与偏差。

    返回损耗后的净 delta 字典。三路（structured/freeform/trpg writeback）
    均调用此函数，确保 AI 自由政令无法绕过损耗。

    field_deltas: 已含玩家角色卡修正后的"目标效果"（structured 路由由调用方先算 scale）。
    seed_keys: 可选 {field: 唯一key} 用于派生偏差 seed；缺省用 field 名。
    """
    loss_factor = execution_loss_factor(state)
    result: dict[str, int] = {}
    for field, delta in field_deltas.items():
        if delta == 0:
            result[field] = 0
            continue
        scaled = delta * loss_factor
        # 保持 apply_base_effects 同向取整约定
        scaled = math.floor(scaled) if scaled > 0 else math.ceil(scaled)
        key = seed_keys.get(field, field) if seed_keys else field
        seed = _derive_seed(state, key)
        mag = max(1, abs(delta) // int(1 / DEVIATION_RATIO)) if DEVIATION_RATIO else 0
        dev = seeded_deviation(seed, mag)
        net = scaled + dev
        # 不因偏差/损耗导致符号翻转（避免 +5 变 -3）
        if delta > 0:
            net = max(0, net)
        elif delta < 0:
            net = min(0, net)
        result[field] = net
    return result
