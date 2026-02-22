"""Position Registry - Central definition of all official positions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PositionCategory(str, Enum):
    """官职类别枚举"""
    CORE = "CORE"
    SECONDARY = "SECONDARY"
    NOBLE = "NOBLE"
    EUNUCH = "EUNUCH"


@dataclass(frozen=True)
class PositionInfo:
    """官职信息结构"""
    category: PositionCategory
    weight: int
    unique: bool
    aliases: tuple[str, ...] = ()


_POSITION_REGISTRY: dict[str, PositionInfo] = {
    # ═══════════════════════════════════════════════════════════════════
    # CORE POSITIONS - 核心职位，全部唯一
    # ═══════════════════════════════════════════════════════════════════

    # 内阁 (5)
    "首辅大学士": PositionInfo(PositionCategory.CORE, 120, True, ("首辅",)),
    "次辅大学士": PositionInfo(PositionCategory.CORE, 115, True, ("次辅",)),
    "东阁大学士": PositionInfo(PositionCategory.CORE, 110, True, ("群辅",)),
    "文渊阁大学士": PositionInfo(PositionCategory.CORE, 110, True),
    "武英殿大学士": PositionInfo(PositionCategory.CORE, 110, True),

    # 吏部 (2)
    "吏部尚书": PositionInfo(PositionCategory.CORE, 100, True),
    "吏部侍郎": PositionInfo(PositionCategory.CORE, 90, True),

    # 户部 (2)
    "户部尚书": PositionInfo(PositionCategory.CORE, 100, True),
    "户部侍郎": PositionInfo(PositionCategory.CORE, 90, True),

    # 礼部 (2)
    "礼部尚书": PositionInfo(PositionCategory.CORE, 100, True),
    "礼部侍郎": PositionInfo(PositionCategory.CORE, 90, True),

    # 兵部 (2)
    "兵部尚书": PositionInfo(PositionCategory.CORE, 100, True),
    "兵部侍郎": PositionInfo(PositionCategory.CORE, 90, True),

    # 刑部 (2)
    "刑部尚书": PositionInfo(PositionCategory.CORE, 100, True),
    "刑部侍郎": PositionInfo(PositionCategory.CORE, 90, True),

    # 工部 (2)
    "工部尚书": PositionInfo(PositionCategory.CORE, 100, True),
    "工部侍郎": PositionInfo(PositionCategory.CORE, 90, True),

    # 都察院 (1)
    "左都御史": PositionInfo(PositionCategory.CORE, 85, True),

    # 锦衣卫 (1)
    "指挥使": PositionInfo(PositionCategory.CORE, 80, True, ("锦衣卫指挥使",)),

    # 地方巡抚 (4) - 各地方唯一
    "辽东巡抚": PositionInfo(PositionCategory.CORE, 80, True),
    "河南巡抚": PositionInfo(PositionCategory.CORE, 80, True),
    "福建巡抚": PositionInfo(PositionCategory.CORE, 80, True),
    "登莱巡抚": PositionInfo(PositionCategory.CORE, 80, True),

    # 地方总兵 (3) - 各镇唯一
    "宣府总兵": PositionInfo(PositionCategory.CORE, 78, True),
    "山海关总兵": PositionInfo(PositionCategory.CORE, 78, True),
    "东江总兵": PositionInfo(PositionCategory.CORE, 78, True),

    # ═══════════════════════════════════════════════════════════════════
    # SECONDARY POSITIONS - 次要职位，全部唯一
    # ═══════════════════════════════════════════════════════════════════

    # 翰林院 (3)
    "翰林学士": PositionInfo(PositionCategory.SECONDARY, 70, True),
    "翰林编修": PositionInfo(PositionCategory.SECONDARY, 60, True),
    "翰林修撰": PositionInfo(PositionCategory.SECONDARY, 60, True),

    # 都察院扩展 (3)
    "左副都御史": PositionInfo(PositionCategory.SECONDARY, 75, True),
    "右佥都御史": PositionInfo(PositionCategory.SECONDARY, 70, True),
    "监察御史": PositionInfo(PositionCategory.SECONDARY, 65, True, ("御史",)),

    # 六部扩展 (6)
    "吏部主事": PositionInfo(PositionCategory.SECONDARY, 60, True),
    "户部主事": PositionInfo(PositionCategory.SECONDARY, 60, True),
    "礼部主事": PositionInfo(PositionCategory.SECONDARY, 60, True),
    "兵部主事": PositionInfo(PositionCategory.SECONDARY, 60, True),
    "刑部主事": PositionInfo(PositionCategory.SECONDARY, 60, True),
    "工部主事": PositionInfo(PositionCategory.SECONDARY, 60, True),

    # 地方扩展 (1)
    "辽东副总兵": PositionInfo(PositionCategory.SECONDARY, 75, True, ("副总兵",)),

    # 六科给事中 (6)
    "吏科给事中": PositionInfo(PositionCategory.SECONDARY, 55, True),
    "户科给事中": PositionInfo(PositionCategory.SECONDARY, 55, True),
    "礼科给事中": PositionInfo(PositionCategory.SECONDARY, 55, True),
    "兵科给事中": PositionInfo(PositionCategory.SECONDARY, 55, True),
    "刑科给事中": PositionInfo(PositionCategory.SECONDARY, 55, True),
    "工科给事中": PositionInfo(PositionCategory.SECONDARY, 55, True),

    # 其他
    "顺天府尹": PositionInfo(PositionCategory.SECONDARY, 60, True),
    "太仆寺卿": PositionInfo(PositionCategory.SECONDARY, 65, True),
    "大理寺卿": PositionInfo(PositionCategory.SECONDARY, 65, True),
    "通政使": PositionInfo(PositionCategory.SECONDARY, 65, True),
    "光禄寺卿": PositionInfo(PositionCategory.SECONDARY, 60, True),

    # ═══════════════════════════════════════════════════════════════════
    # NOBLE POSITIONS - 勋贵，全部唯一
    # ═══════════════════════════════════════════════════════════════════

    "成国公": PositionInfo(PositionCategory.NOBLE, 75, True),
    "英国公": PositionInfo(PositionCategory.NOBLE, 75, True),
    "魏国公": PositionInfo(PositionCategory.NOBLE, 75, True),
    "定国公": PositionInfo(PositionCategory.NOBLE, 70, True),
    "驸马都尉": PositionInfo(PositionCategory.NOBLE, 65, True),
    "嘉定伯": PositionInfo(PositionCategory.NOBLE, 60, True),
    "襄城伯": PositionInfo(PositionCategory.NOBLE, 60, True),

    # ═══════════════════════════════════════════════════════════════════
    # EUNUCH POSITIONS - 内廷，全部唯一
    # ═══════════════════════════════════════════════════════════════════

    "司礼监掌印太监": PositionInfo(PositionCategory.EUNUCH, 75, True, ("掌印太监",)),
    "司礼监太监": PositionInfo(PositionCategory.EUNUCH, 70, True),
    "司礼监秉笔太监": PositionInfo(PositionCategory.EUNUCH, 65, True, ("秉笔太监",)),
}

POSITION_REGISTRY: dict[str, PositionInfo] = _POSITION_REGISTRY


def _build_alias_lookup() -> dict[str, str]:
    """构建别名到规范名的查找表"""
    lookup: dict[str, str] = {}
    for canonical, info in POSITION_REGISTRY.items():
        for alias in info.aliases:
            lookup[alias] = canonical
    return lookup


_ALIAS_LOOKUP = _build_alias_lookup()


def resolve_position(name: str) -> str | None:
    """解析官职名称，支持别名映射到规范名称。"""
    if not name:
        return None
    key = name.strip()
    if key in POSITION_REGISTRY:
        return key
    return _ALIAS_LOOKUP.get(key)


def get_position_info(name: str) -> PositionInfo | None:
    """获取官职信息。"""
    canonical = resolve_position(name)
    if canonical is None:
        return None
    return POSITION_REGISTRY.get(canonical)


def calculate_position_weight(positions: list[str]) -> int:
    """计算累计官职权重。"""
    total = 0
    for pos in positions:
        info = get_position_info(pos)
        if info is not None:
            total += info.weight
    return total


def get_positions_by_category(category: PositionCategory) -> list[str]:
    """获取指定类别的所有官职名称。"""
    return [
        name for name, info in POSITION_REGISTRY.items()
        if info.category == category
    ]


def is_eunuch_position(position: str) -> bool:
    """Check if a position belongs to EUNUCH category."""
    info = get_position_info(position)
    return info is not None and info.category == PositionCategory.EUNUCH


def is_unique_position(position: str) -> bool:
    """Check if a position requires uniqueness (only one holder at a time)."""
    info = get_position_info(position)
    return info is not None and info.unique


def can_appoint(
    minister_eunuch: bool, 
    minister_faction: str, 
    minister_tags: list[str], 
    position: str
) -> bool:
    """Validate if a minister can be appointed to a position.

    Rules:
    - EUNUCH positions can only be held by eunuch ministers (is_eunuch=True)
    - Non-EUNUCH positions can only be held by non-eunuch ministers (is_eunuch=False)
    - Grand Secretariat (内阁) requires the '翰林' tag.
    - Nobles ('勋贵' tag or faction '勋贵集团') can only hold NOBLE positions.
    - Military generals ('武将' tag) cannot be appointed as regional governors (巡抚).

    Args:
        minister_eunuch: Whether the minister is a eunuch
        minister_faction: The minister's faction name
        minister_tags: The minister's personality tags array
        position: The target position name

    Returns:
        True if appointment is valid, False otherwise
    """
    info = get_position_info(position)
    if info is None:
        return False

    # 1. Eunuch vs Civil constraint
    is_eunuch_role = info.category == PositionCategory.EUNUCH
    if minister_eunuch != is_eunuch_role:
        return False

    # 2. Noble constraint
    is_noble_minister = "勋贵" in minister_tags or minister_faction == "勋贵集团"
    if is_noble_minister and info.category != PositionCategory.NOBLE:
        return False
    if not is_noble_minister and info.category == PositionCategory.NOBLE:
        return False

    # 3. Hanlin constraint (Grand Secretariat)
    is_cabinet_role = "大学士" in position
    if is_cabinet_role and "翰林" not in minister_tags:
        return False

    # 4. Military Governor constraint
    is_governor_role = "巡抚" in position
    if is_governor_role and "武将" in minister_tags:
        return False

    return True


__all__ = [
    "PositionCategory",
    "PositionInfo",
    "POSITION_REGISTRY",
    "resolve_position",
    "get_position_info",
    "calculate_position_weight",
    "get_positions_by_category",
    "is_eunuch_position",
    "is_unique_position",
    "can_appoint",
]
