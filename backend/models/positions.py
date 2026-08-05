"""Position Registry - Central definition of all official positions (元末明初版)."""

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
    description: str = ""
    aliases: tuple[str, ...] = ()


_POSITION_REGISTRY: dict[str, PositionInfo] = {
    # ═══════════════════════════════════════════════════════════════════
    # CORE POSITIONS - 核心职位，全部唯一
    # ═══════════════════════════════════════════════════════════════════

    # 中书省 (6) —— 吴王政权中枢，总理军国政务
    "左丞相": PositionInfo(PositionCategory.CORE, 120, True, "中书省长官之首，总领百司，辅佐吴王决断军国大政。", ("左相",)),
    "右丞相": PositionInfo(PositionCategory.CORE, 115, True, "中书省长官，与左丞相同掌朝政，参决机务。", ("右相",)),
    "平章政事": PositionInfo(PositionCategory.CORE, 110, True, "中书省副长官，参预大政，宰执之贰。", ("平章",)),
    "左丞": PositionInfo(PositionCategory.CORE, 100, True, "中书省执政官，分领省事，协理庶政。"),
    "右丞": PositionInfo(PositionCategory.CORE, 100, True, "中书省执政官，分领省事，协理庶政。"),
    "参知政事": PositionInfo(PositionCategory.CORE, 90, True, "中书省参政，与闻大政，位亚执政。", ("参政",)),

    # 大都督府 (2) —— 节制中外诸军事
    "大都督": PositionInfo(PositionCategory.CORE, 110, True, "大都督府长官，节制诸将，总理军旅征伐。"),
    "同知都督": PositionInfo(PositionCategory.CORE, 90, True, "大都督府副长官，佐都督治军，分领兵符。"),

    # 御史台 (2) —— 纠劾百官，肃正纲纪
    "御史大夫": PositionInfo(PositionCategory.CORE, 100, True, "御史台长官，掌纠察百官、整肃风纪。"),
    "治书侍御史": PositionInfo(PositionCategory.CORE, 80, True, "御史台副长官，佐大夫理刑名弹纠。"),

    # ═══════════════════════════════════════════════════════════════════
    # SECONDARY POSITIONS - 次要职位
    # ═══════════════════════════════════════════════════════════════════

    # 幕府文职 (8)
    "中书参政": PositionInfo(PositionCategory.SECONDARY, 70, True, "中书省属官，参佐政务，典领钱谷簿书。"),
    "太史令": PositionInfo(PositionCategory.SECONDARY, 65, True, "掌天文历数、占候推步，参预帷幄谋议。"),
    "博士": PositionInfo(PositionCategory.SECONDARY, 60, True, "掌经史教习与礼制咨议，为儒臣清选。"),
    "都事": PositionInfo(PositionCategory.SECONDARY, 55, True, "中书省属吏首领，出纳文书，督察庶务。"),
    "郎中": PositionInfo(PositionCategory.SECONDARY, 60, True, "分掌部务，典领曹事，为幕府骨干。"),
    "员外郎": PositionInfo(PositionCategory.SECONDARY, 55, True, "郎中副贰，分司文案，协理曹务。"),
    "经历": PositionInfo(PositionCategory.SECONDARY, 50, True, "掌府中案牍往来，检校稽失。"),
    "儒学提举": PositionInfo(PositionCategory.SECONDARY, 55, True, "掌学校教化，课督生徒，振兴文教。"),

    # 军职 (8) —— 非唯一，可多人并任
    "元帅": PositionInfo(PositionCategory.SECONDARY, 65, False, "一军之帅，统率所部征伐守御。"),
    "总管": PositionInfo(PositionCategory.SECONDARY, 60, False, "总领一路军民，镇守要郡。"),
    "判官": PositionInfo(PositionCategory.SECONDARY, 50, False, "佐理军府政务，参决刑名钱谷。"),
    "参军": PositionInfo(PositionCategory.SECONDARY, 50, False, "参谋军事，赞画帷幄，备顾问。"),
    "万户": PositionInfo(PositionCategory.SECONDARY, 45, False, "统兵数千，为军中中级将领。"),
    "镇抚": PositionInfo(PositionCategory.SECONDARY, 40, False, "镇守一方，抚绥军民，弹压盗贼。"),
    "千户": PositionInfo(PositionCategory.SECONDARY, 35, False, "统兵千人，基层武职。"),
    "检校": PositionInfo(PositionCategory.SECONDARY, 45, False, "掌刺事侦伺，察举群下情伪。"),

    # ═══════════════════════════════════════════════════════════════════
    # NOBLE POSITIONS - 勋爵显号，全部唯一
    # ═══════════════════════════════════════════════════════════════════

    "吴国公": PositionInfo(PositionCategory.NOBLE, 75, True, "龙凤政权所封国公爵位，开府江东，威重一方。"),
    "太师": PositionInfo(PositionCategory.NOBLE, 75, True, "三公之首，人臣极品，以示尊崇。"),
    "太尉": PositionInfo(PositionCategory.NOBLE, 70, True, "三公之一，古掌武事，为最高武阶荣衔。"),
    "司徒": PositionInfo(PositionCategory.NOBLE, 65, True, "三公之一，古掌民政，为重臣加衔。"),
    "司空": PositionInfo(PositionCategory.NOBLE, 60, True, "三公之一，古掌水土工事，为元老加衔。"),

    # ═══════════════════════════════════════════════════════════════════
    # EUNUCH POSITIONS - 内廷职位，全部唯一
    # ═══════════════════════════════════════════════════════════════════

    "宣徽使": PositionInfo(PositionCategory.EUNUCH, 60, True, "掌内廷供奉、传宣诏命，为宦官显职。"),
    "内史监令": PositionInfo(PositionCategory.EUNUCH, 55, True, "掌宫禁内侍，典领宦官，出入左右。"),
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
    - 三公/国公等 NOBLE 显号只能授予勋贵之臣（'勋贵' 标签或 '勋贵集团' 派系）
    - 带 '大学士' 之职要求 '翰林' 标签（元末无此职，规则保留兼容）
    - 带 '巡抚' 之职不授武将（元末无此职，规则保留兼容）

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
