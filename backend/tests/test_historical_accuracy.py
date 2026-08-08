"""08-07-historical-accuracy 测试。

验证：
- 各总结类 builder system prompt 含史实段 + 去八股段
- 年号统一格式（至正16年（1356年）3月）注入叙事/奏疏/总评/大臣对话
- 规则C：元末设定下叙事出现"崇祯"被拦截
- parse_freeform_response 缺年号必报错（禁止静默错代）
"""

from ai.prompts import (
    NARRATIVE_SYSTEM_PROMPT,
    MEMORIAL_SYSTEM_PROMPT,
    TURN_COMMENTARY_SYSTEM_PROMPT,
    MINISTER_DIALOGUE_SYSTEM_PROMPT,
    HISTORY_GUARD_CONSTRAINT,
    ANTI_CLICHE_CONSTRAINT,
)
from ai.parsers import parse_freeform_response
from engine.state_consistency import validate_narrative_text
from models.game import (
    GameState,
    Minister,
    MinisterAbilities,
    MinisterStatus,
    MissionState,
    GameTime,
    Region,
    Faction,
)
from models.enums import RegionControl, RegionThreat


def _state(year=1356):
    return GameState(
        time=GameTime(year=year, month=3, era_name="至正", era_year=16 if year == 1356 else year - 1340),
        ministers=[Minister(name="张谋", faction="test", abilities=MinisterAbilities(), loyalty=80, corruption=10)],
        factions=[Faction(name="淮西", satisfaction=60, influence=50, rebellion_risk=20)],
        regions=[Region(name="应天", stability=70, garrison=100, control=RegionControl.COURT, threat=RegionThreat.NONE, civil_morale=65, rebellion_risk=15, disaster_level=0, tax_rate=0.1)],
    )


class TestHistoryGuardInPrompts:
    def test_narrative_has_guards(self):
        assert HISTORY_GUARD_CONSTRAINT in NARRATIVE_SYSTEM_PROMPT
        assert ANTI_CLICHE_CONSTRAINT in NARRATIVE_SYSTEM_PROMPT

    def test_memorial_has_guards(self):
        assert HISTORY_GUARD_CONSTRAINT in MEMORIAL_SYSTEM_PROMPT

    def test_commentary_has_guards(self):
        assert HISTORY_GUARD_CONSTRAINT in TURN_COMMENTARY_SYSTEM_PROMPT

    def test_dialogue_has_guards(self):
        assert HISTORY_GUARD_CONSTRAINT in MINISTER_DIALOGUE_SYSTEM_PROMPT


class TestEraInjection:
    def test_narrative_era_format(self):
        from ai.prompts import build_narrative_prompt
        from models.game import StructuredDecree
        from models.enums import DecreeType
        p = build_narrative_prompt({}, _state(), [], StructuredDecree(type=DecreeType.DISASTER_RELIEF))
        assert "至正16年（1356年）3月" in p


class TestAnachronismRule:
    def test_rejects_chongzhen_in_yuanmo(self):
        s = _state(year=1356)
        issues = validate_narrative_text("次年崇祯帝即位，朝野震荡。", s)
        assert any(i["type"] == "anachronism" for i in issues)

    def test_allows_after_ming_founded(self):
        s = _state(year=1368)
        issues = validate_narrative_text("次年崇祯帝即位，朝野震荡。", s)
        assert not any(i["type"] == "anachronism" for i in issues)

    def test_clean_text_passes(self):
        s = _state(year=1356)
        issues = validate_narrative_text("应天大雪，军民齐心修筑城防。", s)
        assert not any(i["type"] == "anachronism" for i in issues)


class TestParseYearRequired:
    def test_missing_year_errors(self):
        res = parse_freeform_response({"effects": {"global.grain": 100}})
        # 应返回错误 dict（非正常解析）
        assert isinstance(res, dict) and "error" in res

    def test_with_year_ok(self):
        res = parse_freeform_response(
            {"effects": {"global.grain": 100}},
            current_year=1356,
            current_month=3,
        )
        assert "error" not in res
