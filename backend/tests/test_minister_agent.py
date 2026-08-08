"""08-07-minister-agent-enhancement 测试。

验证：
- Minister 八维字段 + clamp_state 覆盖
- build_minister_dialogue_prompt 注入八维 + 独立扮演 persona 段
- 廷议 _vote_reason 按八维+派系差异化（不同大臣理由不同）
- 存档往返兼容（新字段默认）
"""

from ai.prompts import build_minister_dialogue_prompt
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
from models.enums import RegionControl, RegionThreat, DecreeType
from api.assembly_routes import _vote_reason
from models.game import clamp_state


def _minister(name="李善长", **kw):
    return Minister(
        name=name,
        faction=kw.get("faction", "淮西"),
        abilities=MinisterAbilities(
            civil=kw.get("civil", 80),
            military=kw.get("military", 30),
            diplomacy=kw.get("diplomacy", 50),
            administration=kw.get("administration", 70),
            knowledge=kw.get("knowledge", 60),
            politics=kw.get("politics", 75),
        ),
        loyalty=kw.get("loyalty", 70),
        corruption=kw.get("corruption", 20),
        ambition=kw.get("ambition", 40),
        influence=kw.get("influence", 50),
        personality_tags=kw.get("tags", ["沉稳", "谋国"]),
        historical_note="开国功臣",
        biography="辅朱元璋定天下",
        major_contributions=["制律", "理财"],
    )


def _state():
    return GameState(
        time=GameTime(year=1356, month=3, era_name="至正", era_year=16),
        ministers=[_minister()],
        factions=[Faction(name="淮西", satisfaction=60, influence=50, rebellion_risk=20)],
        regions=[Region(name="应天", stability=70, garrison=100, control=RegionControl.COURT, threat=RegionThreat.NONE, civil_morale=65, rebellion_risk=15, disaster_level=0, tax_rate=0.1)],
    )


class TestEightDimensions:
    def test_fields_exist(self):
        m = _minister()
        assert m.abilities.administration == 70
        assert m.abilities.knowledge == 60
        assert m.abilities.politics == 75
        assert m.ambition == 40
        assert m.influence == 50

    def test_clamp_covers_new_fields(self):
        m = Minister.model_construct(name="x", faction="f", abilities=MinisterAbilities.model_construct(
            administration=999, knowledge=-5, politics=200),
            ambition=500, influence=-100)
        s = GameState(ministers=[m])
        clamp_state(s)
        assert 0 <= s.ministers[0].abilities.administration <= 100
        assert 0 <= s.ministers[0].abilities.knowledge <= 100
        assert 0 <= s.ministers[0].abilities.politics <= 100
        assert 0 <= s.ministers[0].ambition <= 100
        assert 0 <= s.ministers[0].influence <= 100

    def test_persistence_roundtrip(self):
        s = _state()
        dumped = s.model_dump_json()
        s2 = GameState.model_validate_json(dumped)
        assert s2.ministers[0].abilities.administration == 70
        assert s2.ministers[0].ambition == 40


class TestDialoguePersona:
    def test_prompt_has_eight_dims(self):
        p = build_minister_dialogue_prompt(_minister(), "试探", _state(), [])
        assert "八维属性" in p
        assert "军事30" in p and "野心40" in p and "势力50" in p

    def test_prompt_has_persona_segment(self):
        p = build_minister_dialogue_prompt(_minister(), "试探", _state(), [])
        assert "【角色扮演】" in p
        assert "独立立场" in p


class TestVoteReasonDifferentiation:
    def test_hawkish_general(self):
        m = _minister(name="徐达", faction="淮西", military=90, ambition=60, civil=30)
        r = _vote_reason(m, "赞成", DecreeType.RECRUIT_TROOPS)
        assert "兵威" in r  # 主战

    def test_civil_steady(self):
        m = _minister(name="李善长", faction="淮西", civil=90, ambition=20, military=20)
        r = _vote_reason(m, "赞成", DecreeType.TAX_DECREASE)
        assert "内政" in r  # 主稳

    def test_different_ministers_differ(self):
        hawk = _minister(name="徐达", faction="淮西", military=90, ambition=60)
        dove = _minister(name="李善长", faction="淮西", civil=90, ambition=20, military=20)
        rh = _vote_reason(hawk, "赞成", DecreeType.RECRUIT_TROOPS)
        rd = _vote_reason(dove, "赞成", DecreeType.RECRUIT_TROOPS)
        assert rh != rd

    def test_faction_stance_reinforced(self):
        m = _minister(name="x", faction="淮西勋将", military=80, ambition=55)
        r = _vote_reason(m, "赞成", DecreeType.RECRUIT_TROOPS)
        # 淮西勋将对 RECRUIT_TROOPS 立场 +10 → 强化
        assert "淮西勋将" in r
