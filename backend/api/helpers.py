from __future__ import annotations

import logging

from models.enums import RegionControl, RegionThreat
from models.game import GameState

logger = logging.getLogger(__name__)

# 枚举字段：str 效果值（如 threat/control）需显式转枚举——直接 setattr 不触发
# pydantic 强转，转枚举保证后续比较一致（阶段D：史实脚本事件清除区域威胁）。
_STR_FIELD_ENUMS: dict[str, object] = {
    "control": RegionControl,
    "threat": RegionThreat,
}


def apply_state_effects(state: GameState, effects: dict[str, int | str]) -> None:
    """应用脚本事件选择的 state_effects（史实主路径效果）。

    数值字段按增量 +=；枚举字段（region.*.threat/control）按字符串直接设置
    （历史推进不可逆——清除后的威胁不会重新施加）。
    """
    for key, delta in effects.items():
        parts = key.split(".")
        if parts[0] == "global" and len(parts) == 2:
            obj, field = state, parts[1]
        elif parts[0] == "region" and len(parts) == 3:
            obj = next((r for r in state.regions if r.name == parts[1]), None)
            field = parts[2]
        elif parts[0] == "faction" and len(parts) == 3:
            obj = next((f for f in state.factions if f.name == parts[1]), None)
            field = parts[2]
        else:
            continue
        if obj is not None and hasattr(obj, field):
            current = getattr(obj, field)
            if isinstance(current, (int, float)) and isinstance(delta, (int, float)):
                setattr(obj, field, current + delta)
            elif isinstance(current, (int, float)):
                # 数值字段收到非数值（str）增量：数据错误，丢弃并记日志（不 500 崩溃）
                logger.warning("apply_state_effects: 数值字段 %s 收到非数值增量 %r", key, delta)
            elif isinstance(current, str) or (
                hasattr(current, "value") and isinstance(current.value, str)
            ):
                enum_cls = _STR_FIELD_ENUMS.get(field)
                if enum_cls is not None and str(delta) in {e.value for e in enum_cls}:
                    setattr(obj, field, enum_cls(str(delta)))
                elif enum_cls is not None:
                    logger.warning(
                        "apply_state_effects: 枚举字段 %s 收到未知枚举值 %r", key, delta
                    )


def apply_loyalty_effects(state: GameState, effects: list[tuple[str, int]]) -> None:
    for name, delta in effects:
        minister = next((m for m in state.ministers if m.name == name), None)
        if minister is not None:
            minister.loyalty += delta

