"""数值区间概念框与阈值硬性预警（08-07-numeric-bands-hard-triggers）。

覆盖：档位边界映射、摘要注入膨胀控制、预警命中/零副作用、prompt 集成断言。
"""
from __future__ import annotations

from engine.numeric_bands import (
    band_of,
    numeric_context,
    region_numeric_context,
    threshold_alerts,
)
from engine.tables import GLOBAL_BANDS, REGION_BANDS
from models.game import GameState, GameTime, INITIAL_FACTIONS, INITIAL_MINISTERS, INITIAL_REGIONS


def make_state(**overrides) -> GameState:
    defaults = dict(
        time=GameTime(year=1360, month=6, era_name="至正", era_year=20),
        national_treasury=15, imperial_treasury=8, grain=420,
        population=1600, military_strength=18,
        civil_morale=62, military_morale=68, court_prestige=62,
        factions=[f.model_copy() for f in INITIAL_FACTIONS],
        regions=[r.model_copy() for r in INITIAL_REGIONS],
        ministers=[m.model_copy() for m in INITIAL_MINISTERS],
    )
    defaults.update(overrides)
    return GameState(**defaults)


# ── T1 全局档位边界 ──────────────────────────────────────

def test_global_band_boundaries():
    bands = GLOBAL_BANDS["civil_morale"]  # lt: 15 崩溃 / 35 危急 / 60 不稳 / 80 平稳 / 101 稳固
    assert band_of(bands, 14)[0] == "崩溃"
    assert band_of(bands, 15)[0] == "危急"
    assert band_of(bands, 34)[0] == "危急"
    assert band_of(bands, 35)[0] == "不稳"
    assert band_of(bands, 60)[0] == "平稳"
    assert band_of(bands, 80)[0] == "稳固"
    assert band_of(bands, 100)[0] == "稳固"


def test_global_band_negative_and_over():
    bands = GLOBAL_BANDS["national_treasury"]
    assert band_of(bands, -5)[0] == "崩溃"
    assert band_of(bands, 999)[0] == "充裕"


def test_band_of_unknown_table_degrades():
    assert band_of(None, 10) is None
    assert band_of([], 10) is None
    assert band_of(GLOBAL_BANDS["grain"], "not-a-number") is None


# ── T2 区域档位（方向相反）────────────────────────────────

def test_region_band_directions():
    # stability 升序：15 以下崩溃
    assert band_of(REGION_BANDS["stability"], 14)[0] == "崩溃"
    assert band_of(REGION_BANDS["stability"], 15)[0] == "动荡"
    assert band_of(REGION_BANDS["stability"], 90)[0] == "稳固"
    # rebellion_risk 降序（越高越危险）
    assert band_of(REGION_BANDS["rebellion_risk"], 71)[0] == "高危"
    assert band_of(REGION_BANDS["rebellion_risk"], 70)[0] == "高危"
    assert band_of(REGION_BANDS["rebellion_risk"], 69)[0] == "上升"
    assert band_of(REGION_BANDS["rebellion_risk"], 39)[0] == "可控"
    assert band_of(REGION_BANDS["rebellion_risk"], 0)[0] == "低危"
    # disaster_level 降序
    assert band_of(REGION_BANDS["disaster_level"], 60)[0] == "大灾"
    assert band_of(REGION_BANDS["disaster_level"], 9)[0] == "安靖"


# ── T3 摘要注入膨胀控制 ───────────────────────────────────

def test_numeric_context_dangerous_expanded():
    state = make_state(civil_morale=10, national_treasury=3)
    ctx = numeric_context(state)
    assert "民心 10（崩溃：民怨沸腾，流民四起）⚠" in ctx
    assert "国库 3（崩溃：府库空虚，度支维艰）⚠" in ctx


def test_numeric_context_stable_no_expansion():
    state = make_state(civil_morale=70, national_treasury=50)
    ctx = numeric_context(state)
    assert "民心 70（平稳）" in ctx
    assert "（民心归附" not in ctx or "（平稳）" in ctx  # 平稳档只标签不展开描述
    assert "⚠" not in ctx


def test_numeric_context_all_stable_single_line_style():
    state = make_state()
    ctx = numeric_context(state)
    assert ctx.startswith("数值区间解读")
    assert "⚠" not in ctx
    assert "\n" not in ctx  # 全平稳：一行总述，只列档位标签不展开描述


def test_region_numeric_context_lists_only_dangerous():
    state = make_state()
    danger = region_numeric_context(state)
    # 初始史实开局即带灾情（两淮/武昌/平江 disaster_level ≥30 灾情档）→ 危险区域非空
    assert danger.startswith("危险区域")
    assert "两淮" in danger and "灾情" in danger
    # 新增稳定度崩溃区域必须出现在摘要中
    state.regions[0].stability = 10
    danger = region_numeric_context(state)
    assert state.regions[0].name in danger
    assert "崩溃" in danger


# ── T4 预警命中/不命中 ────────────────────────────────────

def test_threshold_alerts_hits_on_danger():
    state = make_state(civil_morale=14, national_treasury=4)
    alerts = threshold_alerts(state)
    assert any("民心濒临崩溃" in a for a in alerts)
    assert any("国库空虚" in a for a in alerts)
    assert all(a.startswith("【") for a in alerts)


def test_threshold_alerts_empty_on_stable():
    state = make_state()
    assert threshold_alerts(state) == []


def test_threshold_alerts_multiple_regions():
    state = make_state(military_morale=19)
    state.factions[0].rebellion_risk = 80
    state.regions[0].stability = 10
    alerts = threshold_alerts(state)
    assert len(alerts) >= 3
    assert any("叛乱风险高企" in a for a in alerts)
    assert any("区域秩序崩溃" in a for a in alerts)


def test_threshold_alerts_no_side_effects():
    state = make_state(civil_morale=14)
    before = state.model_dump()
    threshold_alerts(state)
    assert state.model_dump() == before


# ── T5 prompt 集成 ────────────────────────────────────────

def test_narrative_prompt_injects_hard_constraints_when_dangerous():
    from ai.prompts import build_narrative_prompt
    from models.enums import DecreeType
    from models.game import StructuredDecree

    state = make_state(civil_morale=14)
    prompt = build_narrative_prompt(
        {"treasury": 1, "civil_morale": -1, "military_morale": 0, "court_prestige": 0},
        state, [], StructuredDecree(type=DecreeType.TAX_INCREASE),
    )
    assert "【硬性约束】" in prompt
    assert "民怨沸腾" in prompt
    assert "数值区间解读" in prompt


def test_narrative_prompt_no_hard_constraints_when_stable():
    from ai.prompts import build_narrative_prompt
    from models.enums import DecreeType
    from models.game import StructuredDecree

    state = make_state()
    prompt = build_narrative_prompt(
        {"treasury": 1, "civil_morale": 0, "military_morale": 0, "court_prestige": 0},
        state, [], StructuredDecree(type=DecreeType.TAX_INCREASE),
    )
    assert "【硬性约束】" not in prompt


def test_turn_commentary_prompt_injects_numeric_context():
    from ai.prompts import build_turn_commentary_prompt

    state = make_state(civil_morale=30, national_treasury=4)
    prompt = build_turn_commentary_prompt({"year": 1360, "month": 6}, state)
    assert "数值区间解读" in prompt
    assert "【硬性约束】" in prompt
    assert "国库" in prompt


def test_turn_commentary_prompt_no_hard_constraints_when_stable():
    from ai.prompts import build_turn_commentary_prompt

    state = make_state()
    prompt = build_turn_commentary_prompt({"year": 1360, "month": 6}, state)
    assert "【硬性约束】" not in prompt
    assert "数值区间解读" in prompt
