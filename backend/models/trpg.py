"""TRPG（跑团引擎）数据模型：角色卡 / 检定结果 / 行动请求 / 成长记录。

阶段B 新增，独立于治理引擎（engine/），供 backend/trpg/ 与 api/trpg.py 使用。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# ── 常量 ─────────────────────────────────────────────────

# 六维属性（0-100）
ATTR_KEYS: tuple[str, ...] = ("政治", "军事", "学识", "交际", "体力", "胆略")

# 玩家角色名
PLAYER_NAME = "朱元璋"

# 检定结果分级
TIER_CRITICAL_SUCCESS = "critical_success"
TIER_SUCCESS = "success"
TIER_FAILURE = "failure"
TIER_CRITICAL_FAILURE = "critical_failure"

VALID_TIERS = frozenset({
    TIER_CRITICAL_SUCCESS, TIER_SUCCESS, TIER_FAILURE, TIER_CRITICAL_FAILURE,
})

TIER_LABELS: dict[str, str] = {
    TIER_CRITICAL_SUCCESS: "大成功",
    TIER_SUCCESS: "成功",
    TIER_FAILURE: "失败",
    TIER_CRITICAL_FAILURE: "大失败",
}

# 技能 → 检定属性映射（未显式指定属性时按此推断）
SKILL_ATTR_MAP: dict[str, str] = {
    "治军": "军事",
    "统兵": "军事",
    "骑射": "军事",
    "武艺": "胆略",
    "权谋": "政治",
    "理政": "政治",
    "察人": "交际",
    "游说": "交际",
    "招安": "交际",
    "经史": "学识",
    "书法": "学识",
    "兵法": "学识",
    "体魄": "体力",
    "骑术": "体力",
}


# ── CharacterSheet ───────────────────────────────────────

class CharacterSheet(BaseModel):
    """角色卡：玩家（朱元璋）与关键人物共用。"""

    name: str
    is_player: bool = False
    # 六维属性：政治/军事/学识/交际/体力/胆略，0-100
    attrs: dict[str, int] = Field(default_factory=dict)
    # 技能：治军/权谋/察人/书法……，0-100
    skills: dict[str, int] = Field(default_factory=dict)
    background: str = ""
    traits: list[str] = Field(default_factory=list)   # 特质（如"坚韧""多疑"）
    status: list[str] = Field(default_factory=list)   # 状态（伤/病/志气高涨）
    # 未折算的零头技能点（每 5 技能点 = 1 成长点）
    skill_points: int = Field(default=0, ge=0)
    growth_points: int = Field(default=0, ge=0)

    @field_validator("attrs", mode="before")
    @classmethod
    def _normalize_attrs(cls, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("attrs must be a dict")
        normalized: dict[str, int] = {}
        for key, raw in value.items():
            if not isinstance(key, str):
                continue
            try:
                v = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"attr {key} must be an integer")
            if not (0 <= v <= 100):
                raise ValueError(f"attr {key} out of range 0-100: {v}")
            normalized[key] = v
        return normalized

    @field_validator("skills", mode="before")
    @classmethod
    def _normalize_skills(cls, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("skills must be a dict")
        normalized: dict[str, int] = {}
        for key, raw in value.items():
            if not isinstance(key, str):
                continue
            try:
                v = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"skill {key} must be an integer")
            if not (0 <= v <= 100):
                raise ValueError(f"skill {key} out of range 0-100: {v}")
            normalized[key] = v
        return normalized

    def attr(self, name: str) -> int:
        return self.attrs.get(name, 0)

    def skill(self, name: str | None) -> int | None:
        if not name:
            return None
        return self.skills.get(name)


# ── RollResult ───────────────────────────────────────────

class RollResult(BaseModel):
    """D100 检定结果。"""

    roll: int = Field(ge=1, le=100)          # 1-100
    target: int = Field(ge=1, le=100)        # 属性+技能修正+DC 后的目标值
    tier: str                                # 四档分级，见 VALID_TIERS
    dc: int = 0                              # 难度修正（简易+20/常规0/困难-20/极难-40）
    attr_name: str | None = None
    skill_name: str | None = None

    @field_validator("tier")
    @classmethod
    def _validate_tier(cls, value):
        if value not in VALID_TIERS:
            raise ValueError(f"invalid tier: {value}")
        return value


# ── ActRequest ───────────────────────────────────────────

class ActRequest(BaseModel):
    """POST /api/trpg/act 请求体。"""

    action_text: str = Field(min_length=1, max_length=500)
    skill: str | None = Field(default=None, max_length=50)
    # 可选：显式指定检定属性；缺省时按 skill 推断，再缺省用"胆略"
    attr: str | None = Field(default=None, max_length=10)
    # 难度：简易/常规/困难/极难（兼容 easy/normal/hard/extreme）
    difficulty: str = "常规"


# ── GrowthEntry ──────────────────────────────────────────

class GrowthEntry(BaseModel):
    """成长记录（写入存档 growth_log，随角色卡可查）。"""

    year: int
    month: int
    name: str
    source: str                    # 来源：叙事回合/关键事件:xxx/学习……
    skill_points: int = Field(default=0, ge=0)
    growth_points: int = Field(default=0, ge=0)
    attr_name: str | None = None
    attr_gain: int = Field(default=0, ge=0)
