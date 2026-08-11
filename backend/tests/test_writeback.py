"""阶段D 步骤4：GM state_changes 应用层 + 治理→跑团回写钩子（design 第 3.2 节）。"""
import random

import pytest

from engine.core import process_decree, update_region_control
from models.enums import DecreeType, MinisterStatus, RegionControl
from models.game import GameState, StructuredDecree, create_initial_state
from models.trpg import PLAYER_NAME
from trpg import character as character_mod
from trpg import writeback as wb


def _state_with_sheets() -> GameState:
    state = create_initial_state()
    character_mod.ensure_sheets(state)
    return state


def _player_sheet(state: GameState):
    return state.character_sheets[PLAYER_NAME]


# ── apply_state_changes：白名单应用层 ────────────────────

class TestApplyStateChanges:
    def test_valid_global_int_applied(self):
        state = _state_with_sheets()
        result = wb.apply_state_changes(state, {"global.civil_morale": -3})
        assert result == {"applied": ["global.civil_morale"], "ignored": []}
        assert state.civil_morale == 59

    def test_whitelist_unknown_and_system_fields_ignored(self):
        state = _state_with_sheets()
        before = state.model_dump()
        result = wb.apply_state_changes(state, {
            "global.phase": "governance",       # 系统字段不在白名单
            "global.character_sheets": {},      # 系统字段不在白名单
            "foo.bar": 1,                       # 未知键
        })
        assert result["applied"] == []
        assert set(result["ignored"]) == {"global.phase", "global.character_sheets", "foo.bar"}
        assert state.model_dump() == before     # 全量拒绝，状态不变

    def test_type_error_rejected(self):
        state = _state_with_sheets()
        result = wb.apply_state_changes(state, {"global.grain": "很多"})
        assert result["ignored"] == ["global.grain"]
        assert state.grain == 420

    def test_missing_entity_ignored(self):
        state = _state_with_sheets()
        result = wb.apply_state_changes(state, {"minister.不存在的人.loyalty": -5})
        assert result["ignored"] == ["minister.不存在的人.loyalty"]

    def test_str_enum_field_coerced(self):
        """region.*.control 等枚举字段：白名单校验后显式转枚举，保证后续比较一致。"""
        state = _state_with_sheets()
        region = next(r for r in state.regions if r.name == "应天")
        result = wb.apply_state_changes(state, {"region.应天.control": "失控"})
        assert result["applied"] == ["region.应天.control"]
        assert region.control is RegionControl.UNSTABLE

    def test_str_invalid_value_rejected(self):
        state = _state_with_sheets()
        result = wb.apply_state_changes(state, {"region.应天.control": "半壁江山"})
        assert result["ignored"] == ["region.应天.control"]

    def test_minister_status_enum_coerced(self):
        state = _state_with_sheets()
        minister = next(m for m in state.ministers if m.name == "徐达")
        result = wb.apply_state_changes(state, {"minister.徐达.status": "removed"})
        assert result["applied"] == ["minister.徐达.status"]
        assert minister.status is MinisterStatus.REMOVED

    def test_minister_abilities_and_float_region_applied(self):
        state = _state_with_sheets()
        minister = next(m for m in state.ministers if m.name == "徐达")
        before_civil = minister.abilities.civil
        region = next(r for r in state.regions if r.name == "应天")
        before_rate = region.tax_rate
        result = wb.apply_state_changes(state, {
            "minister.徐达.abilities.civil": 5,
            "region.应天.tax_rate": 0.05,
        })
        assert set(result["applied"]) == {"minister.徐达.abilities.civil", "region.应天.tax_rate"}
        assert minister.abilities.civil == before_civil + 5
        assert abs(region.tax_rate - round(before_rate + 0.05, 2)) < 1e-6

    def test_non_dict_changes_returns_empty(self):
        state = _state_with_sheets()
        assert wb.apply_state_changes(state, "oops") == {"applied": [], "ignored": []}


# ── 治理 → 跑团回写钩子单测 ──────────────────────────────

class TestWritebackHooks:
    def test_defeat_applies_military_minus2_and_status(self):
        state = _state_with_sheets()
        before = _player_sheet(state).attrs["军事"]
        assert wb.writeback_defeat(state) is True
        sheet = _player_sheet(state)
        assert sheet.attrs["军事"] == before - 2
        assert "挫败" in sheet.status

    def test_defeat_one_shot_per_game(self):
        """以"挫败"状态为闸口：同局仅回写一次，防连续战败反复扣属性。"""
        state = _state_with_sheets()
        before = _player_sheet(state).attrs["军事"]
        assert wb.writeback_defeat(state) is True
        assert wb.writeback_defeat(state) is False
        assert _player_sheet(state).attrs["军事"] == before - 2

    def test_civil_collapse_applies_political_minus2(self):
        state = _state_with_sheets()
        before = _player_sheet(state).attrs["政治"]
        assert wb.writeback_civil_collapse(state) is True
        assert _player_sheet(state).attrs["政治"] == before - 2

    def test_betrayal_trait_granted_effectively(self):
        """叛离回写实际授予"多疑"（初始特质已不含，钩子为唯一来源）。"""
        state = _state_with_sheets()
        sheet = _player_sheet(state)
        assert "多疑" not in sheet.traits          # 阶段D 校准：初始特质不含
        assert wb.writeback_minister_betrayal(state, "杨宪") is True
        assert "多疑" in sheet.traits
        # 幂等：已有多疑不重复添加
        assert wb.writeback_minister_betrayal(state, "杨宪") is True
        assert sheet.traits.count("多疑") == 1

    def test_betrayal_trait_does_not_consume_global_random(self, monkeypatch):
        state = _state_with_sheets()
        sheet = _player_sheet(state)
        monkeypatch.setattr(
            random,
            "random",
            lambda: (_ for _ in ()).throw(AssertionError("global RNG consumed")),
        )
        assert wb.writeback_minister_betrayal(state, "杨宪") is True
        assert "多疑" in sheet.traits

    def test_hooks_skip_without_player_sheet(self):
        """角色卡缺失（新档未生成）时安全跳过，不抛错。"""
        state = create_initial_state()  # 无 character_sheets
        assert wb.writeback_defeat(state) is False
        assert wb.writeback_civil_collapse(state) is False
        assert wb.writeback_minister_betrayal(state, "杨宪") is False
        assert wb.apply_betrayal_check(state) == []

    def test_betrayal_check_registers_zero_loyalty_once(self):
        state = _state_with_sheets()
        # 新档开局 1328-10 大臣均未入仕，显式激活一名
        minister = next(m for m in state.ministers if m.status == MinisterStatus.NOT_YET_ENTERED)
        minister.status = MinisterStatus.ACTIVE
        minister.loyalty = 0
        assert wb.apply_betrayal_check(state) == [minister.name]
        assert minister.name in state.loyalty_zero_triggered
        # 已登记：不再重复触发
        assert wb.apply_betrayal_check(state) == []


# ── process_decree 挂载点集成 ────────────────────────────

class TestWritebackMounts:
    def _state_with_region_at_brink(self):
        state = _state_with_sheets()
        region = next(r for r in state.regions if r.name == "应天")
        region.control = RegionControl.UNSTABLE
        region.stability = 5      # update_region_control → FALLEN
        return state

    def test_region_fall_triggers_defeat_writeback(self):
        state = self._state_with_region_at_brink()
        before_mil = _player_sheet(state).attrs["军事"]
        # TAX_INCREASE 压低区域稳定度（应天 5 → 更低），结算后应天沦陷 → 战败回写
        process_decree(state, StructuredDecree(type=DecreeType.TAX_INCREASE))
        sheet = _player_sheet(state)
        assert sheet.attrs["军事"] == before_mil - 2
        assert "挫败" in sheet.status

    def test_update_region_control_returns_newly_fallen(self):
        state = self._state_with_region_at_brink()
        newly_fallen = update_region_control(state)
        assert newly_fallen == ["应天"]
        # 非新沦陷轮次返回空
        assert update_region_control(state) == []

    def test_civil_collapse_crossing_triggers_writeback(self):
        """结算后民心从阈值上方落入崩溃区间 → 政治 -2；低民心期间不再重复。"""
        state = _state_with_sheets()
        state.civil_morale = 11    # 阈值 10 上方
        before_pol = _player_sheet(state).attrs["政治"]
        # TAX_INCREASE civil_morale -5 → 6，落入崩溃区间
        process_decree(state, StructuredDecree(type=DecreeType.TAX_INCREASE))
        assert _player_sheet(state).attrs["政治"] == before_pol - 2
        # 仍在低民心：下一轮不重复（穿越检测）
        process_decree(state, StructuredDecree(type=DecreeType.TAX_INCREASE))
        assert _player_sheet(state).attrs["政治"] == before_pol - 2

    def test_no_collapse_writeback_when_morale_healthy(self):
        state = _state_with_sheets()
        before_pol = _player_sheet(state).attrs["政治"]
        process_decree(state, StructuredDecree(type=DecreeType.TAX_DECREASE))
        assert _player_sheet(state).attrs["政治"] == before_pol
