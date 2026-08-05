"""角色卡 CRUD 与成长计算。

成长规则（初版数量级，阶段D平衡基准）：
- 每叙事回合约产出 1-2 技能点；关键事件完成另奖 2-5 技能点。
- 每 5 技能点 = 1 成长点 → 属性 +1（上限 100）。
- 玩家初始主属性约 40-55。

growth_points 语义：未消费的成长点余量。检定奖励折算的成长点若指定了
属性则自动投入（属性 +1），未投入部分留在 growth_points 供后续使用。
"""
from __future__ import annotations

import zlib

from models.game import GameState, Minister
from models.trpg import ATTR_KEYS, PLAYER_NAME, CharacterSheet, GrowthEntry

# ── 常量 ─────────────────────────────────────────────────

SKILL_POINTS_PER_GROWTH = 5
ATTR_CAP = 100

# 每叙事回合技能点：基础 1 点，成功/大成功 +1（即 1-2 点）
NARRATIVE_TURN_POINTS_BASE = 1
NARRATIVE_TURN_POINTS_SUCCESS_BONUS = 1

# 关键事件奖励（2-5 区间取中值，阶段D可调）
KEY_EVENT_POINTS = 3

# 玩家初始属性（主属性 40-55）
PLAYER_INITIAL_ATTRS: dict[str, int] = {
    "政治": 45,
    "军事": 50,
    "学识": 40,
    "交际": 45,
    "体力": 55,
    "胆略": 50,
}
PLAYER_INITIAL_SKILLS: dict[str, int] = {
    "治军": 30,
    "察人": 25,
    "权谋": 20,
    "书法": 15,
}
PLAYER_BACKGROUND = (
    "濠州钟离贫农出身，幼年牧牛；至正四年灾疫丧亲，入皇觉寺为行童，"
    "托钵云游淮西数年；至正十二年投郭子兴红巾军，以骁勇任亲兵九夫长。"
)
PLAYER_TRAITS = ["坚韧", "多疑", "志向远大"]

# 关键人物名单（与 ministers.json 交集生成角色卡）
KEY_FIGURE_NAMES: tuple[str, ...] = (
    "徐达", "常遇春", "李善长", "刘基", "朱升", "汤和",
    "陈友谅", "张士诚", "明玉珍", "方国珍", "扩廓帖木儿",
)


# ── 角色卡生成 ───────────────────────────────────────────

def _stable_bonus(seed_text: str, span: int = 21) -> int:
    """按名字生成确定性随机加成（0..span-1），避免内置 hash() 的进程随机性。"""
    return zlib.crc32(seed_text.encode("utf-8")) % span


def create_player_sheet() -> CharacterSheet:
    return CharacterSheet(
        name=PLAYER_NAME,
        is_player=True,
        attrs=dict(PLAYER_INITIAL_ATTRS),
        skills=dict(PLAYER_INITIAL_SKILLS),
        background=PLAYER_BACKGROUND,
        traits=list(PLAYER_TRAITS),
        status=[],
    )


def _minister_skills(minister: Minister) -> dict[str, int]:
    """由大臣三维能力派生技能（确定性）。"""
    skills: dict[str, int] = {}
    if minister.abilities.military >= 60:
        skills["治军"] = max(1, minister.abilities.military - 10)
    if minister.abilities.civil >= 60:
        skills["权谋"] = max(1, minister.abilities.civil - 10)
    if minister.abilities.diplomacy >= 60:
        skills["游说"] = max(1, minister.abilities.diplomacy - 10)
    return skills


def create_sheet_from_minister(minister: Minister) -> CharacterSheet:
    """由 ministers.json 数据派生关键人物角色卡（六维确定性映射）。"""
    name = minister.name
    civil = minister.abilities.civil
    military = minister.abilities.military
    diplomacy = minister.abilities.diplomacy
    attrs = {
        "政治": civil,
        "军事": military,
        "学识": max(0, min(100, civil + _stable_bonus(f"{name}:学识", 11) - 5)),
        "交际": diplomacy,
        "体力": 40 + _stable_bonus(f"{name}:体力"),
        "胆略": 40 + _stable_bonus(f"{name}:胆略"),
    }
    return CharacterSheet(
        name=name,
        is_player=False,
        attrs=attrs,
        skills=_minister_skills(minister),
        background=minister.historical_note or "",
        traits=list(minister.personality_tags),
        status=[],
    )


def build_initial_sheets(ministers: list[Minister] | None = None) -> dict[str, CharacterSheet]:
    """构建玩家 + 关键人物角色卡表。"""
    if ministers is None:
        from models.game import get_initial_ministers
        ministers = get_initial_ministers()
    sheets: dict[str, CharacterSheet] = {PLAYER_NAME: create_player_sheet()}
    key_set = set(KEY_FIGURE_NAMES)
    for minister in ministers:
        if minister.name in key_set:
            sheets[minister.name] = create_sheet_from_minister(minister)
    return sheets


# ── CRUD（作用于 GameState.character_sheets）─────────────

def ensure_sheets(state: GameState) -> dict[str, CharacterSheet]:
    """存档中无角色卡时惰性初始化（新档/旧档迁移后首访）。"""
    if not state.character_sheets:
        state.character_sheets = build_initial_sheets(state.ministers or None)
    return state.character_sheets


def get_sheet(state: GameState, name: str) -> CharacterSheet | None:
    return state.character_sheets.get(name)


def set_sheet(state: GameState, sheet: CharacterSheet) -> None:
    state.character_sheets[sheet.name] = sheet


def remove_sheet(state: GameState, name: str) -> bool:
    return state.character_sheets.pop(name, None) is not None


# ── 成长计算 ─────────────────────────────────────────────

def convert_skill_points(sheet: CharacterSheet) -> int:
    """把累计技能点按每 5 点折算为成长点，返回本次折算数量。"""
    if sheet.skill_points < SKILL_POINTS_PER_GROWTH:
        return 0
    converted = sheet.skill_points // SKILL_POINTS_PER_GROWTH
    sheet.skill_points -= converted * SKILL_POINTS_PER_GROWTH
    sheet.growth_points += converted
    return converted


def spend_growth_point(sheet: CharacterSheet, attr_name: str) -> bool:
    """消耗 1 成长点 → 指定属性 +1（上限 100）。属性已满或无成长点则失败。"""
    if sheet.growth_points <= 0:
        return False
    if attr_name not in sheet.attrs or sheet.attrs[attr_name] >= ATTR_CAP:
        return False
    sheet.growth_points -= 1
    sheet.attrs[attr_name] += 1
    return True


def award_skill_points(
    state: GameState,
    name: str,
    points: int,
    source: str,
    attr_name: str | None = None,
) -> GrowthEntry | None:
    """奖励技能点：累计折算成长点，并（若指定属性）自动投入属性 +1。

    成长记录写入 state.growth_log（随存档持久化）。角色不存在返回 None。
    """
    if points <= 0:
        return None
    sheet = get_sheet(state, name)
    if sheet is None:
        return None
    sheet.skill_points += points
    converted = convert_skill_points(sheet)
    attr_gain = 0
    if converted > 0 and attr_name and attr_name in sheet.attrs:
        attr_gain = min(converted, ATTR_CAP - sheet.attrs[attr_name])
        sheet.attrs[attr_name] += attr_gain
        sheet.growth_points -= attr_gain  # 已自动投入属性，不再计入未消费余量
    entry = GrowthEntry(
        year=state.time.year,
        month=state.time.month,
        name=name,
        source=source,
        skill_points=points,
        growth_points=converted,
        attr_name=attr_name if attr_gain > 0 else None,
        attr_gain=attr_gain,
    )
    state.growth_log.append(entry)
    return entry


def narrative_turn_points(tier: str) -> int:
    """每叙事回合技能点产出：成功/大成功 2 点，其余 1 点（初版 1-2 点契约）。"""
    from models.trpg import TIER_CRITICAL_SUCCESS, TIER_SUCCESS
    if tier in (TIER_SUCCESS, TIER_CRITICAL_SUCCESS):
        return NARRATIVE_TURN_POINTS_BASE + NARRATIVE_TURN_POINTS_SUCCESS_BONUS
    return NARRATIVE_TURN_POINTS_BASE


def complete_key_event_with_growth(state: GameState, milestone_id: str) -> dict | None:
    """完成关键事件：推进篇章（chapter.py）并另奖技能点（2-5 取中值 3）。"""
    from trpg import chapter as chapter_mod
    result = chapter_mod.complete_key_event(state, milestone_id)
    if result is None:
        return None
    entry = award_skill_points(
        state,
        PLAYER_NAME,
        KEY_EVENT_POINTS,
        source=f"关键事件:{result['title']}",
        attr_name=None,  # 关键事件奖励暂存成长点，由后续检定折算投入
    )
    result["growth"] = entry.model_dump() if entry else None
    return result
