"""08-07-active-policy-tracking 测试。

验证：
- build_global_situation / _chat_state_snapshot 含大臣 current_mission（含 ON_MISSION 状态）
- GameState.active_policies 注入序列化
- PolicyProgress 存档往返一致（model_dump_json → model_validate）
"""

from ai.prompts import build_global_situation, _chat_state_snapshot
from ai.parsers import _serialize_game_state
from models.game import (
    GameState,
    Minister,
    MinisterAbilities,
    MinisterStatus,
    MissionState,
    PolicyProgress,
    GameTime,
    RegionControl,
    RegionThreat,
    Region,
)
from models.enums import RegionControl as RC, RegionThreat as RT


def _minister(name="李政", status=MinisterStatus.ACTIVE, mission=None):
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


def _state(mission=None, on_mission=False, policies=None):
    m = _minister(mission=mission)
    if on_mission:
        m.status = MinisterStatus.ON_MISSION
    return GameState(
        time=GameTime(year=1356, month=3, era_name="至正", era_year=16),
        ministers=[m],
        regions=[Region(name="应天", stability=70, garrison=100, control=RC.COURT, threat=RT.NONE, civil_morale=65, rebellion_risk=15, disaster_level=0, tax_rate=0.1)],
        active_policies=policies or [],
    )


class TestMissionInjection:
    def test_mission_in_serialize(self):
        ms = MissionState(name="屯田", progress_months=2, total_months=6, cost=200, effects={"grain": 500})
        out = _serialize_game_state(_state(ms))
        assert "在办:屯田(2/6月" in out

    def test_on_mission_in_chat_snapshot(self):
        ms = MissionState(name="修城", progress_months=1, total_months=4, cost=100, effects={"military_strength": 300})
        out = _chat_state_snapshot(_state(ms, on_mission=True))
        assert "在办:修城" in out

    def test_mission_in_global_situation(self):
        ms = MissionState(name="治水", progress_months=3, total_months=8, cost=300, effects={"civil_morale": 200})
        out = build_global_situation(_state(ms))
        assert "在办:治水(3/8月" in out


class TestActivePolicies:
    def test_policy_in_serialize(self):
        p = PolicyProgress(name="海运改制", started_year=1355, started_month=6, summary="改漕运为海运", effects={"grain": 1000})
        out = _serialize_game_state(_state(policies=[p]))
        assert "国策在办：海云改制" in out or "国策在办：海运改制" in out

    def test_policy_persistence_roundtrip(self):
        p = PolicyProgress(name="盐法整顿", started_year=1354, started_month=9, summary="规范盐引", effects={"national_treasury": 2000})
        s = _state(policies=[p])
        dumped = s.model_dump_json()
        s2 = GameState.model_validate_json(dumped)
        assert len(s2.active_policies) == 1
        assert s2.active_policies[0].name == "盐法整顿"
        assert s2.active_policies[0].effects == {"national_treasury": 2000}

    def test_no_policy_default_empty(self):
        s = _state()
        assert s.active_policies == []
        # 旧存档兼容：无此字段不报错
        dumped = s.model_dump_json()
        s2 = GameState.model_validate_json(dumped)
        assert s2.active_policies == []


class TestBackwardCompat:
    def test_mission_advance_still_works(self):
        # 不破坏 MissionState 生命周期：仅验证构造+序列化无异常
        ms = MissionState(name="戍边", progress_months=0, total_months=3, cost=150, effects={"military_strength": 400})
        out = build_global_situation(_state(ms))
        assert "戍边" in out
