"""08-07-ai-memory-decree-prompts 测试：统一全局势上下文 + CoT 约束。

验证：
- build_global_situation 含年号、数值区间、REMOVED 守卫、在办任务。
- 5 个总结类 builder 的 system prompt 含 COT 约束段。
- 拒绝 RAG 约束出现在叙事/总评 system prompt。
"""

from ai.prompts import (
    build_global_situation,
    build_narrative_prompt,
    build_memorial_prompt,
    build_turn_commentary_prompt,
    build_minister_reaction_prompt,
    build_minister_dialogue_prompt,
    COT_CONSTRAINT,
    NARRATIVE_SYSTEM_PROMPT,
    TURN_COMMENTARY_SYSTEM_PROMPT,
    MEMORIAL_SYSTEM_PROMPT,
)
from models.game import (
    GameState,
    Minister,
    MinisterAbilities,
    MinisterStatus,
    MissionState,
    GameTime,
    Faction,
    Region,
)
from models.enums import RegionControl, RegionThreat


def _minister(name="张谋", status=MinisterStatus.ACTIVE, mission=None):
    m = Minister(
        name=name,
        faction="test",
        abilities=MinisterAbilities(civil=70, military=50, diplomacy=60),
        loyalty=80,
        corruption=10,
        status=status,
    )
    if mission:
        m.current_mission = mission
    return m


def _state():
    return GameState(
        time=GameTime(year=1356, month=3, era_name="至正", era_year=16),
        ministers=[_minister()],
        factions=[Faction(name="淮西", satisfaction=60, influence=50, rebellion_risk=20)],
        regions=[Region(name="应天", stability=70, garrison=100, control=RegionControl.COURT, threat=RegionThreat.NONE, civil_morale=65, rebellion_risk=15, disaster_level=0, tax_rate=0.1)],
    )


# ── build_global_situation ──────────────────────────────

class TestGlobalSituation:
    def test_era_injection(self):
        out = build_global_situation(_state())
        assert "至正16年（1356年）3月" in out

    def test_prompt_guard_present(self):
        s = _state()
        s.ministers.append(_minister("已死", status=MinisterStatus.REMOVED))
        out = build_global_situation(s)
        # REMOVED 守卫文案（state_consistency.build_prompt_guard）
        assert "已死" in out and ("不得" in out or "禁止" in out or "不可" in out)

    def test_mission_injection(self):
        mission = MissionState(name="屯田", progress_months=2, total_months=6, cost=200, effects={"grain": 500})
        s = _state()
        s.ministers[0].current_mission = mission
        out = build_global_situation(s)
        assert "在办:屯田(2/6月" in out

    def test_on_mission_visible(self):
        mission = MissionState(name="修城", progress_months=1, total_months=4, cost=100, effects={"military_strength": 300})
        s = _state()
        s.ministers[0].status = MinisterStatus.ON_MISSION
        s.ministers[0].current_mission = mission
        out = build_global_situation(s)
        # ON_MISSION 不被跳过
        assert "在办:修城" in out


# ── CoT 约束 ────────────────────────────────────────────

class TestCotConstraint:
    def test_narrative_has_cot(self):
        assert COT_CONSTRAINT in NARRATIVE_SYSTEM_PROMPT

    def test_memorial_has_cot(self):
        assert COT_CONSTRAINT in MEMORIAL_SYSTEM_PROMPT

    def test_commentary_has_cot(self):
        assert COT_CONSTRAINT in TURN_COMMENTARY_SYSTEM_PROMPT

    def test_reaction_has_cot(self):
        from ai.prompts import MINISTER_REACTION_SYSTEM_PROMPT
        assert COT_CONSTRAINT in MINISTER_REACTION_SYSTEM_PROMPT

    def test_dialogue_has_cot(self):
        from ai.prompts import MINISTER_DIALOGUE_SYSTEM_PROMPT
        assert COT_CONSTRAINT in MINISTER_DIALOGUE_SYSTEM_PROMPT

    def test_reject_rag_in_narrative(self):
        assert "拒绝 RAG" in NARRATIVE_SYSTEM_PROMPT

    def test_reject_rag_in_commentary(self):
        assert "拒绝 RAG" in TURN_COMMENTARY_SYSTEM_PROMPT


# ── builder 输出一致性 ──────────────────────────────────

class TestBuilders:
    def test_narrative_uses_global_situation(self):
        from models.game import StructuredDecree
        from models.enums import DecreeType
        s = _state()
        prompt = build_narrative_prompt({}, s, [], StructuredDecree(type=DecreeType.DISASTER_RELIEF))
        # 年号来自统一序列化
        assert "至正16年（1356年）3月" in prompt

    def test_memorial_contains_era(self):
        s = _state()
        prompt = build_memorial_prompt("试探", s.ministers[0], s)
        assert "至正16年（1356年）3月" in prompt
