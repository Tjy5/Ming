"""跑团 ↔ 治理数据互通契约（父 design 第 7 节，方向一）。

`get_player_modifiers(state)` 按玩家角色卡计算政令结算修正：
- 军事类政令 ← 军事；内政类 ← 政治；外交/招安类 ← 交际；文教/基建类 ← 学识。
- 修正公式：success_mod = (attr - 50) / 100，±0.5 封顶。
- 胆略/体力不直接作用于政令，仅用于跑团检定与特殊事件。

本阶段只提供契约实现，不接入 engine 结算（阶段D接入）。
"""
from __future__ import annotations

from models.game import GameState
from models.trpg import PLAYER_NAME

MODIFIER_CAP = 0.5

# 政令类别 → 角色属性 映射（键为 engine 政令类别 + culture 供文教/基建）
CATEGORY_ATTR_MAP: dict[str, str] = {
    "military": "军事",
    "domestic": "政治",
    "diplomacy": "交际",
    "culture": "学识",   # 文教/基建（阶段D明确归属的具体政令）
}


def success_mod(attr_value: int) -> float:
    """单属性修正：(attr - 50) / 100，封顶 ±0.5。"""
    return max(-MODIFIER_CAP, min(MODIFIER_CAP, (attr_value - 50) / 100))


def get_player_modifiers(state: GameState) -> dict[str, float]:
    """玩家角色卡 → 政令结算修正表。

    返回形如 {"military": 0.12, "domestic": -0.05, ...}；
    玩家角色卡缺失时返回空表（引擎侧按无修正处理）。
    """
    sheet = state.character_sheets.get(PLAYER_NAME)
    if sheet is None:
        return {}
    modifiers: dict[str, float] = {}
    for category, attr_name in CATEGORY_ATTR_MAP.items():
        value = sheet.attrs.get(attr_name)
        if value is None:
            continue
        modifiers[category] = success_mod(value)
    return modifiers
