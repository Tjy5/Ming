from __future__ import annotations

"""数值区间概念框与阈值硬性预警（优点B5：AI 生成与确定性规则混合控制）。

- 概念框（GLOBAL_BANDS / REGION_BANDS）：把绝对数值映射为区间语义标签+描述，
  注入 AI prompt，弥补模型对绝对数值理解弱的问题。
- 阈值预警（THRESHOLD_ALERTS）：数值触达危险区间时生成"必须/禁止"语义的强制
  叙事口径提示——只约束 AI 输出，不修改任何状态（与 CHAIN_EVENTS 职责分离）。

纯函数模块，不 import ai/ 层；被 ai/prompts.py 惰性引用（防 engine 初始化环）。
"""

import logging

from engine.tables import (
    DANGEROUS_BAND_LABELS,
    GLOBAL_BANDS,
    REGION_BANDS,
    THRESHOLD_ALERTS,
)
from models.game import GameState

logger = logging.getLogger(__name__)

_GLOBAL_LABELS = {
    "national_treasury": "国库",
    "imperial_treasury": "内帑",
    "grain": "粮储",
    "population": "人口",
    "military_strength": "军力",
    "civil_morale": "民心",
    "military_morale": "军心",
    "court_prestige": "威望",
}

# 需要展开描述的指标（危险/关键），避免 prompt 膨胀；其余指标只列档位标签。
_EXPANDED_GLOBAL = {"national_treasury", "civil_morale", "military_morale", "court_prestige"}

_REGION_LABELS = {
    "stability": "稳定度",
    "civil_morale": "民心",
    "rebellion_risk": "叛乱风险",
    "disaster_level": "灾情",
}


def band_of(bands: list, value) -> tuple[str, str] | None:
    """按档位表判定 value 的 (标签, 描述)。升序（lt）从低到高、降序（ge）从高到低首中；
    未命中返回最后一档；表缺失/非数值安全降级返回 None。"""
    if not bands:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    for kind, limit, label, desc in bands:
        if kind == "lt" and value < limit:
            return label, desc
        if kind == "ge" and value >= limit:
            return label, desc
    label, desc = bands[-1][2], bands[-1][3]
    return label, desc


def _is_dangerous(band: tuple[str, str] | None) -> bool:
    return bool(band) and band[0] in DANGEROUS_BAND_LABELS


def numeric_context(state: GameState) -> str:
    """当前关键数值的区间语义摘要（确定性生成，注入 AI prompt）。

    膨胀控制（design 2.2）：危险档（⚠）逐行展开描述；无危险档时一行总述只列档位标签。
    """
    lines: list[str] = []
    for field, label in _GLOBAL_LABELS.items():
        value = getattr(state, field, None)
        if value is None:
            continue
        band = band_of(GLOBAL_BANDS.get(field), value)
        if band is None:
            continue
        tag, desc = band
        if field in _EXPANDED_GLOBAL and _is_dangerous(band):
            lines.append(f"{label} {int(value)}（{tag}：{desc}）⚠ 危险区间，叙事必须如实反映")
        else:
            lines.append(f"{label} {int(value)}（{tag}）")
    if not lines:
        return ""
    if not any("⚠" in line for line in lines):
        return "数值区间解读（供叙事口径参考）：" + "、".join(lines)
    return "数值区间解读（供叙事口径参考）：\n" + "\n".join(f"- {line}" for line in lines)


def region_numeric_context(state: GameState) -> str:
    """危险区域摘要：只列命中危险档位的区域——稳定度 崩溃/动荡、民心 崩溃/危急、
    叛乱风险 高危/上升、灾情 大灾/灾情；其余区域不列（防 prompt 膨胀）。"""
    lines: list[str] = []
    for r in state.regions:
        parts: list[str] = []
        for field in ("stability", "civil_morale", "rebellion_risk", "disaster_level"):
            band = band_of(REGION_BANDS.get(field), getattr(r, field))
            if band is not None and _is_dangerous(band):
                label = _REGION_LABELS.get(field, field)
                parts.append(f"{label} {getattr(r, field)}（{band[0]}）")
        if parts:
            lines.append(f"- {r.name}：" + "、".join(parts))
    return "危险区域：\n" + "\n".join(lines) if lines else ""


def threshold_alerts(state: GameState) -> list[str]:
    """命中 THRESHOLD_ALERTS 的强制叙事口径提示。只读 state，无副作用。"""
    hits: list[str] = []
    for name, check, message in THRESHOLD_ALERTS:
        try:
            if check(state):
                hits.append(f"【{name}】{message}。")
        except Exception:
            logger.warning("threshold alert check failed", extra={"alert": name})
    return hits
