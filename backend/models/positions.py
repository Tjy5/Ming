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
    description: str = ""
    aliases: tuple[str, ...] = ()


_POSITION_REGISTRY: dict[str, PositionInfo] = {
    # ═══════════════════════════════════════════════════════════════════
    # CORE POSITIONS - 核心职位，全部唯一
    # ═══════════════════════════════════════════════════════════════════

    # 内阁 (5)
    "首辅大学士": PositionInfo(PositionCategory.CORE, 120, True, "内阁之首，掌握票拟权，辅佐皇帝处理政务，为实权宰辅。", ("首辅",)),
    "次辅大学士": PositionInfo(PositionCategory.CORE, 115, True, "内阁次席，协助首辅处理票拟，地位尊崇。", ("次辅",)),
    "东阁大学士": PositionInfo(PositionCategory.CORE, 110, True, "内阁辅臣，参与机务，主要负责奏章处理与政令拟定。", ("群辅",)),
    "文渊阁大学士": PositionInfo(PositionCategory.CORE, 110, True, "内阁辅臣，参与草拟诏敕，参与机密政务。"),
    "武英殿大学士": PositionInfo(PositionCategory.CORE, 110, True, "内阁辅臣，多负责儒道经筵或典章编纂，亦预机务。"),

    # 吏部 (2)
    "吏部尚书": PositionInfo(PositionCategory.CORE, 100, True, "天官，掌管全国官吏的任免、考课、升降、调动，权势极重。"),
    "吏部侍郎": PositionInfo(PositionCategory.CORE, 90, True, "吏部副长官，协助尚书处理官吏选拔与考课事务。"),

    # 户部 (2)
    "户部尚书": PositionInfo(PositionCategory.CORE, 100, True, "掌管全国疆土、田地、户籍、赋税、俸饷及财政收支。"),
    "户部侍郎": PositionInfo(PositionCategory.CORE, 90, True, "户部副长官，分管财政支拨与田赋征收。"),

    # 礼部 (2)
    "礼部尚书": PositionInfo(PositionCategory.CORE, 100, True, "掌管典礼、祭祀、学校、科举考试及外交事务。"),
    "礼部侍郎": PositionInfo(PositionCategory.CORE, 90, True, "礼部副长官，协助处理礼仪、贡举及外事。"),

    # 兵部 (2)
    "兵部尚书": PositionInfo(PositionCategory.CORE, 100, True, "掌管全国武官选授、简练、兵籍、军械、驿传及军令。"),
    "兵部侍郎": PositionInfo(PositionCategory.CORE, 90, True, "兵部副长官，协助处理军备与武官任免。"),

    # 刑部 (2)
    "刑部尚书": PositionInfo(PositionCategory.CORE, 100, True, "掌管全国法律、刑狱、案件核定及监狱管理。"),
    "刑部侍郎": PositionInfo(PositionCategory.CORE, 90, True, "刑部副长官，协助审理重大案件与刑罚复核。"),

    # 工部 (2)
    "工部尚书": PositionInfo(PositionCategory.CORE, 100, True, "掌管全国土木兴建、水利工程、矿冶及军器制造。"),
    "工部侍郎": PositionInfo(PositionCategory.CORE, 90, True, "工部副长官，分管营建工程与工官考核。"),

    # 都察院 (1)
    "左都御史": PositionInfo(PositionCategory.CORE, 85, True, "掌管全国监察权，负责弹劾奸邪、整肃纲纪、纠正冤狱。"),

    # 锦衣卫 (1)
    "指挥使": PositionInfo(PositionCategory.CORE, 80, True, "锦衣卫首领，掌管御前侍卫、侦察、逮捕及审理钦定案件。", ("锦衣卫指挥使",)),

    # 地方巡抚 (4) - 各地方唯一
    "辽东巡抚": PositionInfo(PositionCategory.CORE, 80, True, "代天子巡治辽东，统筹一省之军民政务，为国家边防重镇长官。"),
    "河南巡抚": PositionInfo(PositionCategory.CORE, 80, True, "负责河南军务与民政，在明末主要应对流民起义与河道治理。"),
    "福建巡抚": PositionInfo(PositionCategory.CORE, 80, True, "负责福建军务、海防及民政，侧重于海上安全与对外交涉。"),
    "登莱巡抚": PositionInfo(PositionCategory.CORE, 80, True, "镇守登州、莱州，负责海防勤王，支持辽东前线。"),

    # 地方总兵 (3) - 各镇唯一
    "宣府总兵": PositionInfo(PositionCategory.CORE, 78, True, "镇守宣府，北方长城重镇主官，负责防御内蒙古及通州防御。"),
    "山海关总兵": PositionInfo(PositionCategory.CORE, 78, True, "负责山海关防务，守卫京师大门，协助辽东作战。"),
    "东江总兵": PositionInfo(PositionCategory.CORE, 78, True, "由于远在海外，负责在敌后牵制后金，为辽东侧翼屏障。"),

    # ═══════════════════════════════════════════════════════════════════
    # SECONDARY POSITIONS - 次要职位，全部唯一
    # ═══════════════════════════════════════════════════════════════════

    # 翰林院 (3)
    "翰林学士": PositionInfo(PositionCategory.SECONDARY, 70, True, "翰林院长官，掌管撰写诏敕、修史及侍从皇帝讲论经史。"),
    "翰林编修": PositionInfo(PositionCategory.SECONDARY, 60, True, "负责纂修国史、起草文书，为清贵的储才官职。"),
    "翰林修撰": PositionInfo(PositionCategory.SECONDARY, 60, True, "负责编纂实录及诏书，主要由状元授职，前程远大。"),

    # 都察院扩展 (3)
    "左副都御史": PositionInfo(PositionCategory.SECONDARY, 75, True, "副监察长官，协助都御史巡查地方、纠察官员。"),
    "右佥都御史": PositionInfo(PositionCategory.SECONDARY, 70, True, "具有监察职能的官员，常兼任地方总督巡抚，协调民政与监察。"),
    "监察御史": PositionInfo(PositionCategory.SECONDARY, 65, True, "代天子巡狩，巡历地方，具备极大的纠劾、行政监察权。", ("御史",)),

    # 六部扩展 (6)
    "吏部主事": PositionInfo(PositionCategory.SECONDARY, 60, True, "部内各司办事官，负责具体的吏政治理与文案处理。"),
    "户部主事": PositionInfo(PositionCategory.SECONDARY, 60, True, "负责具体财税统计、钱粮调度及地方税课管理。"),
    "礼部主事": PositionInfo(PositionCategory.SECONDARY, 60, True, "部内办事官，负责集礼、礼仪制度的具体执行。"),
    "兵部主事": PositionInfo(PositionCategory.SECONDARY, 60, True, "部内办事官，负责具体的军令下达与防务协调。"),
    "刑部主事": PositionInfo(PositionCategory.SECONDARY, 60, True, "部内办事官，负责具体案件的卷宗审核与法律适用。"),
    "工部主事": PositionInfo(PositionCategory.SECONDARY, 60, True, "部内办事官，负责具体的工程监督与物资申领。"),

    # 地方扩展 (1)
    "辽东副总兵": PositionInfo(PositionCategory.SECONDARY, 75, True, "协助总兵统领辽东精锐，负责具体的作战指挥与戍卫。", ("副总兵",)),

    # 六科给事中 (6)
    "吏科给事中": PositionInfo(PositionCategory.SECONDARY, 55, True, "负责监督吏部政务，具有封驳诏敕、谏诤及弹劾之权。"),
    "户科给事中": PositionInfo(PositionCategory.SECONDARY, 55, True, "监督户部，审核国家经费开支，纠察财政违失。"),
    "礼科给事中": PositionInfo(PositionCategory.SECONDARY, 55, True, "监督礼部，规范典礼执行，谏言礼法改革。"),
    "兵科给事中": PositionInfo(PositionCategory.SECONDARY, 55, True, "监督兵部，审察军政得失，监察边防要务。"),
    "刑科给事中": PositionInfo(PositionCategory.SECONDARY, 55, True, "监督刑部，参与疑狱复审，纠察司法不当。"),
    "工科给事中": PositionInfo(PositionCategory.SECONDARY, 55, True, "监督工部，核查营建开支，监察工程质量。"),

    # 其他
    "顺天府尹": PositionInfo(PositionCategory.SECONDARY, 60, True, "掌管京城土地、户籍及财政民政，职级高于普通府尹。"),
    "太仆寺卿": PositionInfo(PositionCategory.SECONDARY, 65, True, "掌管全国马匹繁育、牧放及马政储备，支持骑兵建设。"),
    "大理寺卿": PositionInfo(PositionCategory.SECONDARY, 65, True, "掌管国家刑罚复核，与刑部、都察院并称‘三法司’。"),
    "通政使": PositionInfo(PositionCategory.SECONDARY, 65, True, "掌管全国臣民奏章的出纳与上达，为皇帝的耳目传声筒。"),
    "光禄寺卿": PositionInfo(PositionCategory.SECONDARY, 60, True, "掌管宫廷祭祀、宴飨及外宾膳食，管理皇室给养。"),

    # ═══════════════════════════════════════════════════════════════════
    # NOBLE POSITIONS - 勋贵，全部唯一
    # ═══════════════════════════════════════════════════════════════════

    "成国公": PositionInfo(PositionCategory.NOBLE, 75, True, "世袭勋爵，勋臣之首，常参与重要朝议及统领营兵。"),
    "英国公": PositionInfo(PositionCategory.NOBLE, 75, True, "世袭勋爵，地位崇高，在勋门中具备极高的威望与资历。"),
    "魏国公": PositionInfo(PositionCategory.NOBLE, 75, True, "南京世袭勋爵，明初名将之后，镇卫南京。"),
    "定国公": PositionInfo(PositionCategory.NOBLE, 70, True, "世袭勋爵，明代功臣后裔，负责京师治安及禁卫。"),
    "驸马都尉": PositionInfo(PositionCategory.NOBLE, 65, True, "皇帝的女婿，职位尊崇，常参与外事接待及宗人府事务。"),
    "嘉定伯": PositionInfo(PositionCategory.NOBLE, 60, True, "外戚勋爵，后妃母家，代表皇室亲族势力。"),
    "襄城伯": PositionInfo(PositionCategory.NOBLE, 60, True, "世袭勋爵，武臣之勋，具备领兵训练及皇室守卫职责。"),

    # ═══════════════════════════════════════════════════════════════════
    # EUNUCH POSITIONS - 内廷，全部唯一
    # ═══════════════════════════════════════════════════════════════════

    "司礼监掌印太监": PositionInfo(PositionCategory.EUNUCH, 75, True, "内廷最具实权者，掌管司礼监印章，负责批红，可抗衡甚至指挥内阁。", ("掌印太监",)),
    "司礼监太监": PositionInfo(PositionCategory.EUNUCH, 70, True, "内廷重臣，协助掌印、秉笔处理内廷与外廷政务。"),
    "司礼监秉笔太监": PositionInfo(PositionCategory.EUNUCH, 65, True, "负责代皇帝批红，对朝政影响力巨大。", ("秉笔太监",)),

    # ═══════════════════════════════════════════════════════════════════
    # NOBLE POSITIONS (extended)
    # ═══════════════════════════════════════════════════════════════════

    "保国公": PositionInfo(PositionCategory.NOBLE, 70, True, "世袭勋爵，勋臣之一，参与朝议及营兵统领。"),
    "新城侯": PositionInfo(PositionCategory.NOBLE, 65, True, "世袭侯爵，勋臣后裔，参与军事及仪仗。"),
    "英国公世子": PositionInfo(PositionCategory.NOBLE, 60, True, "英国公爵位继承人，以世子身份参与朝廷事务。"),

    # ═══════════════════════════════════════════════════════════════════
    # SECONDARY POSITIONS (extended)
    # ═══════════════════════════════════════════════════════════════════

    "巡抚": PositionInfo(PositionCategory.SECONDARY, 70, False, "代天子巡行地方，掌管一省或数府军政事务。"),
    "总兵": PositionInfo(PositionCategory.SECONDARY, 65, False, "一镇最高军事长官，负责辖区内军务。"),
    "副将": PositionInfo(PositionCategory.SECONDARY, 60, False, "军中副将，协助总兵统领一镇兵马。"),
    "大学士": PositionInfo(PositionCategory.SECONDARY, 80, False, "内阁成员通称，参与国家机务与诏敕拟定。"),
    "陕西参政": PositionInfo(PositionCategory.SECONDARY, 65, True, "陕西布政司参政，分管省内政务与财政。"),
    "陕西参议": PositionInfo(PositionCategory.SECONDARY, 60, True, "陕西按察司参议，协助巡察省内官员。"),
    "南阳知府": PositionInfo(PositionCategory.SECONDARY, 60, True, "南阳府最高行政长官，掌管民政、财政与司法。"),
    "大名知府": PositionInfo(PositionCategory.SECONDARY, 60, True, "大名府最高行政长官，管治地方军民政事务。"),
    "北镇抚司": PositionInfo(PositionCategory.SECONDARY, 60, True, "锦衣卫北镇抚司主官，负责钦定案件的侦缉与审讯。"),
    "湖广佥事": PositionInfo(PositionCategory.SECONDARY, 55, True, "湖广按察司辅官，负责司法刑名与地方巡察。"),
    "参将": PositionInfo(PositionCategory.SECONDARY, 55, False, "镇守地方或随征的中级军官。"),
    "千总": PositionInfo(PositionCategory.SECONDARY, 40, False, "基层军官，统领千人，负责戍守与作战。"),
    "知府": PositionInfo(PositionCategory.SECONDARY, 55, False, "一府之行政长官，掌管府内政务民生。"),
    "知县": PositionInfo(PositionCategory.SECONDARY, 40, False, "一县之行政长官，负责赋税诉讼与教化。"),
    "教谕": PositionInfo(PositionCategory.SECONDARY, 35, False, "县学教官，负责科举教育与士子管理。"),
    "翰林侍读": PositionInfo(PositionCategory.SECONDARY, 55, False, "翰林院侍读，负责经筵讲学与典籍编纂。"),
    "光禄少卿": PositionInfo(PositionCategory.SECONDARY, 55, False, "光禄寺副长官，协助掌管宫廷宴飨与祭祀供品。"),
    "太常少卿": PositionInfo(PositionCategory.SECONDARY, 55, False, "太常寺副长官，协助掌管宗庙礼仪与祭祀事务。"),
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
