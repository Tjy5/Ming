"""阶段D集成测试：时间轴对齐（开局 1328-10）+ 切换端点与 phase 翻转。

覆盖（implement.md 第 1、2 步）：
- 新档开局时间 1328-10、chapter=childhood、phase=life_story（里程碑日期锚点）；
- 完成童年章末里程碑（famine-1344）→ 章推进 + 时间对齐里程碑日期 1344-04；
- 完成 yingtian-founding → phase=governance、时间=1356-03、角色卡/成长日志
  状态连续、过渡叙事写入 history_log、存档快照写入（回滚点）；
- 未知里程碑 → 404；
- governance 后完成里程碑 → 不翻 phase、无异常。
步骤 4-5（design 第 3 节）：GM state_changes 应用层 + 政令效果修正。
"""
import asyncio
import json

import pytest
from fastapi import HTTPException

from ai.provider import ResilientProvider
from fakes import FakeProvider
from api import routes as api_routes
from api import state as api_state
from api import trpg as trpg_routes
from api.schemas import DecreeRequest
from db import saves as db_saves
from engine.core import inject_script_events, process_decree
from models.enums import DecreeType, RegionThreat
from models.game import GameTime, StructuredDecree, create_initial_state
from models.trpg import PLAYER_NAME, ActRequest, ConvergeRequest
from trpg import chapter as chapter_mod
from trpg import character as character_mod


def _fake_provider():
    return ResilientProvider(FakeProvider(), timeout=1, retries=1)


@pytest.fixture(autouse=True)
def _restore_globals():
    old_state = api_state._state
    old_provider = api_state._provider
    try:
        yield
    finally:
        api_state._state = old_state
        api_state._provider = old_provider


# ── 时间轴对齐：开局 1328-10 ─────────────────────────────

class TestOpeningTimeline:
    def test_new_game_starts_at_birth_milestone(self):
        state = create_initial_state()
        assert state.time.year == 1328
        assert state.time.month == 10
        assert state.time.era_name == "天历"
        assert state.time.era_year == 1
        assert state.phase == "life_story"
        assert state.chapter == "childhood"

    def test_opening_time_matches_birth_milestone(self):
        """开局时间与 birth-1328 里程碑日期一致（里程碑日期锚点模型）。"""
        milestone = next(
            m for m in chapter_mod.get_milestones() if m.get("id") == "birth-1328"
        )
        state = create_initial_state()
        assert state.time.year == int(milestone["year"])
        assert state.time.month == int(milestone["month"])


# ── 时间轴对齐：完成里程碑 → 时间对齐里程碑日期 ──────────

class TestMilestoneTimeAlignment:
    def test_famine_1344_advances_chapter_and_aligns_time(self):
        api_state._state = create_initial_state()
        resp = asyncio.run(trpg_routes.complete_milestone("famine-1344"))

        assert resp["milestone"] == "famine-1344"
        assert resp["title"] == "灾疫丧亲，入皇觉寺"
        assert resp["transition"] is not None
        assert resp["transition"]["to_chapter"] == "monk_wanderer"
        assert resp["phase"] == "life_story"

        state = api_state._state
        assert state.chapter == "monk_wanderer"
        # 章推进（advance_chapter 跳年 1344-01）后，时间对齐到里程碑日期 1344-04
        assert state.time.year == 1344
        assert state.time.month == 4
        assert state.time.era_name == "至正"
        assert state.time.era_year == 4
        # 关键事件成长奖励写入（源字符串与 character.py 一致）
        assert len(state.growth_log) == 1
        assert state.growth_log[0].source == "关键事件:灾疫丧亲，入皇觉寺"
        # 完成叙事入历史（feed 回放机制同 /act）
        assert state.history_log[-1].decree_type == "trpg_act"
        assert "岁月流转" in state.history_log[-1].narrative
        # 未翻 phase：life_story 阶段无过渡叙事标记
        assert "阶段切换" not in state.history_log[-1].narrative


# ── phase 翻转：yingtian-founding ────────────────────────

class TestPhaseSwitch:
    def _state_in_warlord_with_growth(self) -> None:
        state = create_initial_state()
        state.chapter = "warlord"
        character_mod.ensure_sheets(state)
        character_mod.award_skill_points(state, PLAYER_NAME, 5, "叙事回合", "军事")
        api_state._state = state

    def test_yingtian_founding_switches_to_governance(
        self, monkeypatch, tmp_path,
    ):
        monkeypatch.setattr(db_saves, "DB_PATH", tmp_path / "saves.db")
        db_saves.init_db()
        self._state_in_warlord_with_growth()
        attrs_before = api_state._state.character_sheets[PLAYER_NAME].attrs.copy()

        resp = asyncio.run(trpg_routes.complete_milestone("yingtian-founding"))

        assert resp["milestone"] == "yingtian-founding"
        assert resp["phase"] == "governance"
        assert resp["transition"] is None  # 非 warlord 末里程碑
        assert resp["frozen"] is True

        state = api_state._state
        assert state.phase == "governance"
        # 时间对齐到 phase_switch 配置日期 1356-03
        assert state.time.year == 1356
        assert state.time.month == 3
        assert state.time.era_name == "至正"
        assert state.time.era_year == 16

        # 状态连续：角色卡原样保留（属性不因切换改变，仅成长记录追加关键事件条目）
        assert state.character_sheets[PLAYER_NAME].attrs == attrs_before
        assert len(state.growth_log) == 2
        assert state.growth_log[-1].source == "关键事件:克集庆，改应天府"

        # 过渡叙事写入 history_log（decree_type=trpg_act，引用 phase_switch.note）
        entry = state.history_log[-1]
        assert entry.decree_type == "trpg_act"
        assert entry.year == 1356 and entry.month == 3
        assert "阶段切换" in entry.narrative
        assert "治理模拟" in entry.narrative

        # 存档快照写入（回滚点）
        saves = db_saves.list_saves()
        assert len(saves) == 1
        assert "阶段切换快照" in saves[0]["name"]

    def test_phase_switch_reference_fields_in_response(self):
        """响应与 /act 同构：milestone/title/narrative/time/growth/chapter 齐备。"""
        api_state._state = create_initial_state()
        api_state._state.chapter = "warlord"
        resp = asyncio.run(trpg_routes.complete_milestone("yingtian-founding"))
        for key in ("milestone", "title", "narrative", "transition", "growth",
                    "phase", "chapter", "chapter_title", "time"):
            assert key in resp
        assert resp["time"]["era_name"] == "至正"

    def test_yingtian_completion_no_time_rewind(self):
        """1360-03 时完成 yingtian-founding（日期 1356-03）→ 200、phase→governance、时间不回拨。"""
        state = create_initial_state()
        state.chapter = "warlord"
        state.time = GameTime(year=1360, month=3, era_name="至正", era_year=20)
        api_state._state = state
        resp = asyncio.run(trpg_routes.complete_milestone("yingtian-founding"))
        assert resp["phase"] == "governance"
        assert resp["milestone"] == "yingtian-founding"
        assert api_state._state.phase == "governance"
        assert api_state._state.time.year == 1360
        assert api_state._state.time.month == 3
        assert api_state._state.time.era_name == "至正"
        assert api_state._state.time.era_year == 20


# ── 边界：未知里程碑 / governance 内完成 ──────────────────

class TestEdgeCases:
    def test_unknown_milestone_returns_404(self):
        api_state._state = create_initial_state()
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(trpg_routes.complete_milestone("不存在的里程碑"))
        assert exc_info.value.status_code == 404
        detail = exc_info.value.detail
        assert detail["error_code"] == "milestone_not_found"
        # 失败不落盘：resolved_script_ids 未被污染
        assert api_state._state.resolved_script_ids == set()

    def test_famine_duplicate_rejected_409(self):
        """重复完成同一里程碑 → 409：成长点不重复发放、章/时间/已解析集均不变。"""
        api_state._state = create_initial_state()
        asyncio.run(trpg_routes.complete_milestone("famine-1344"))
        state = api_state._state
        assert len(state.growth_log) == 1
        resolved_before = set(state.resolved_script_ids)
        time_before = state.time.model_dump()

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(trpg_routes.complete_milestone("famine-1344"))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["error_code"] == "milestone_already_resolved"

        # 409 不落盘：成长记录不新增、时间/章不回退、已解析集不变化
        assert len(state.growth_log) == 1
        assert state.time.model_dump() == time_before
        assert state.chapter == "monk_wanderer"
        assert set(state.resolved_script_ids) == resolved_before

    def test_milestone_in_governance_no_phase_flip(self):
        state = create_initial_state()
        state.phase = "governance"
        state.chapter = "warlord"
        api_state._state = state

        # 非 phase_switch 里程碑：时间对齐仍生效，phase 保持 governance
        resp = asyncio.run(trpg_routes.complete_milestone("zhedong-talents-1360"))
        assert resp["phase"] == "governance"
        state = api_state._state
        assert state.phase == "governance"
        assert state.time.year == 1360
        assert state.time.month == 3
        assert "zhedong-talents-1360" in state.resolved_script_ids

    def test_completed_yingtian_rejected_409_in_governance(
        self, monkeypatch, tmp_path,
    ):
        """governance 内再调已完成里程碑 → 409：时间不回拨、快照不新增。"""
        monkeypatch.setattr(db_saves, "DB_PATH", tmp_path / "saves.db")
        db_saves.init_db()
        state = create_initial_state()
        state.phase = "governance"
        state.chapter = "warlord"
        api_state._state = state

        # 首次完成：governance 内允许（未解析），不翻 phase、不写快照
        resp = asyncio.run(trpg_routes.complete_milestone("yingtian-founding"))
        assert resp["phase"] == "governance"
        assert resp["transition"] is None          # is_frozen → advance_chapter 返回 None
        assert "阶段切换" not in resp["narrative"]  # 不重复触发过渡叙事
        assert api_state._state.phase == "governance"
        assert db_saves.list_saves() == []          # 不重复写快照

        # 二次完成：409 拒绝，时间保持 1356-03 不回拨
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(trpg_routes.complete_milestone("yingtian-founding"))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["error_code"] == "milestone_already_resolved"
        assert api_state._state.time.model_dump() == resp["time"]
        assert db_saves.list_saves() == []

    def test_governance_completes_last_chapter_milestone_without_error(self):
        """warlord 末里程碑（ming-proclamation）在 governance 内完成：不翻 phase、无异常。"""
        state = create_initial_state()
        state.phase = "governance"
        state.chapter = "warlord"
        api_state._state = state
        resp = asyncio.run(trpg_routes.complete_milestone("ming-proclamation"))
        assert resp["phase"] == "governance"
        assert resp["transition"] is None
        assert api_state._state.phase == "governance"


# ── 1360 收束抉择（design 第 2.3 节）──────────────────────

class TestConvergence:
    def _warlord_at_1360(self):
        state = create_initial_state()
        state.chapter = "warlord"
        state.time = GameTime(year=1360, month=3, era_name="至正", era_year=20)
        return state

    def test_act_attaches_convergence_options_when_hook_active(self):
        api_state._provider = _fake_provider()
        api_state._state = self._warlord_at_1360()
        resp = asyncio.run(trpg_routes.act(ActRequest(action_text="整顿残军")))
        assert resp["convergence_hook"] is not None
        convergence_options = [o for o in resp["options"] if o.get("convergence")]
        assert len(convergence_options) == 2
        assert {o["convergence"] for o in convergence_options} == {"accept", "refuse"}
        assert {o["option_id"] for o in convergence_options} == {
            "opt_converge_accept", "opt_converge_refuse",
        }

    def test_act_no_convergence_options_before_fallback(self):
        api_state._provider = _fake_provider()
        api_state._state = create_initial_state()  # 1328-10 < 1360
        resp = asyncio.run(trpg_routes.act(ActRequest(action_text="牧牛于野")))
        assert resp["convergence_hook"] is None
        assert not any(o.get("convergence") for o in resp["options"])

    def test_act_no_convergence_in_governance(self):
        """governance（is_frozen）不触发收束。"""
        api_state._provider = _fake_provider()
        state = self._warlord_at_1360()
        state.phase = "governance"
        api_state._state = state
        resp = asyncio.run(trpg_routes.act(ActRequest(action_text="治理中的辅助检定")))
        assert resp["convergence_hook"] is None
        assert not any(o.get("convergence") for o in resp["options"])
        assert resp["frozen"] is True

    def test_converge_accept_switches_governance(self, monkeypatch, tmp_path):
        monkeypatch.setattr(db_saves, "DB_PATH", tmp_path / "saves.db")
        db_saves.init_db()
        api_state._state = self._warlord_at_1360()

        resp = asyncio.run(trpg_routes.converge(ConvergeRequest(choice="accept")))

        assert resp["choice"] == "accept"
        assert resp["phase"] == "governance"
        assert resp["converged_milestone"] == "yingtian-founding"
        assert resp["game_over"] is None

        state = api_state._state
        assert state.phase == "governance"
        # 时间对齐 fallback_year=1360（保留当前月份）
        assert state.time.year == 1360
        assert state.time.month == 3
        assert state.time.era_name == "至正"
        assert state.time.era_year == 20
        # yingtian-founding 视为已达成 → 完成端点 409 闸口联动
        assert "yingtian-founding" in state.resolved_script_ids
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(trpg_routes.complete_milestone("yingtian-founding"))
        assert exc_info.value.status_code == 409
        # 过渡叙事入历史
        entry = state.history_log[-1]
        assert entry.decree_type == "trpg_act"
        assert "收束" in entry.narrative
        assert entry.year == 1360
        # 存档快照（回滚点）
        saves = db_saves.list_saves()
        assert len(saves) == 1
        assert "收束切换快照" in saves[0]["name"]

    def test_converge_refuse_defeat_branch(self):
        api_state._state = self._warlord_at_1360()
        resp = asyncio.run(trpg_routes.converge(ConvergeRequest(choice="refuse")))

        assert resp["choice"] == "refuse"
        assert resp["game_over"] is not None
        assert resp["game_over"]["result"] == "defeat"
        assert resp["phase"] == "life_story"
        assert resp["converged_milestone"] is None

        state = api_state._state
        assert state.phase == "life_story"           # 不翻 phase
        assert "yingtian-founding" not in state.resolved_script_ids
        assert state.time.year == 1360
        entry = state.history_log[-1]
        assert entry.decree_type == "trpg_act"
        assert "身死" in entry.narrative
        # 结局不持久化（同治理侧口径）：重载后收束钩子仍可再触发
        assert chapter_mod.check_convergence_hook(state) is not None

    def test_converge_without_pending_hook_409(self):
        api_state._state = create_initial_state()  # 1328-10 未到兜底年
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(trpg_routes.converge(ConvergeRequest(choice="accept")))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["error_code"] == "convergence_not_pending"
        # 失败不落盘
        assert api_state._state.resolved_script_ids == set()


# ── GM state_changes 应用层（design 第 3.2 节）────────────

class TestStateChangesApplication:
    def test_act_rule_fallback_returns_empty_result(self):
        """规则回退 state_changes 恒 {} → applied/ignored 均空（向后兼容）。"""
        api_state._provider = _fake_provider()
        api_state._state = create_initial_state()
        resp = asyncio.run(trpg_routes.act(ActRequest(action_text="巡查营寨")))
        assert resp["state_changes_result"] == {"applied": [], "ignored": []}
        assert "state_changes" in resp  # 原始字段保留

    def test_act_applies_ai_state_changes(self):
        class _StateChangeProvider(FakeProvider):
            async def chat_query(self, text, game_state, history):
                return json.dumps({
                    "narrative": "整饬一新，军心稍定。",
                    "options": [
                        {"option_id": "a", "label": "甲"},
                        {"option_id": "b", "label": "乙"},
                        {"option_id": "c", "label": "丙"},
                    ],
                    "state_changes": {
                        "global.civil_morale": 3,
                        "global.phase": "governance",   # 系统字段 → 忽略
                    },
                }, ensure_ascii=False)

        api_state._provider = ResilientProvider(_StateChangeProvider(), timeout=1, retries=1)
        api_state._state = create_initial_state()
        before = api_state._state.civil_morale
        resp = asyncio.run(trpg_routes.act(ActRequest(action_text="整饬军纪")))
        assert resp["state_changes_result"]["applied"] == ["global.civil_morale"]
        assert resp["state_changes_result"]["ignored"] == ["global.phase"]
        assert api_state._state.civil_morale == before + 3


# ── 跑团 → 治理数据互通：政令效果修正（design 第 3.1 节）─

class TestDecreeModifier:
    def _state_with_military(self, attr_value):
        state = create_initial_state()
        state.character_sheets[PLAYER_NAME] = character_mod.create_player_sheet()
        state.character_sheets[PLAYER_NAME].attrs["军事"] = attr_value
        return state

    def _military_gain(self, state, decree_type):
        before = state.military_strength
        process_decree(state, StructuredDecree(type=decree_type))
        return state.military_strength - before

    def _baseline_gain(self, decree_type):
        """无角色卡（{}）→ 不修正，作为幅度基准（漂移等噪声两路一致）。"""
        return self._military_gain(create_initial_state(), decree_type)

    def test_military_decree_scaled_by_military_attr_capped(self):
        # 军事 100 → success_mod +0.5 封顶 → RECRUIT_TROOPS 军力 +8 → +12
        state = self._state_with_military(100)
        gain = self._military_gain(state, DecreeType.RECRUIT_TROOPS)
        assert gain - self._baseline_gain(DecreeType.RECRUIT_TROOPS) == 4

    def test_military_decree_low_attr_scales_down(self):
        # 军事 0 → success_mod -0.5 → +8 → +4
        state = self._state_with_military(0)
        gain = self._military_gain(state, DecreeType.RECRUIT_TROOPS)
        assert gain - self._baseline_gain(DecreeType.RECRUIT_TROOPS) == -4

    def test_other_category_decree_not_modified(self):
        """PERSONNEL（other 类）不修正：带角色卡与不带完全一致。"""
        state = self._state_with_military(100)
        before = state.military_strength
        process_decree(state, StructuredDecree(type=DecreeType.PERSONNEL))
        gain_with_sheet = state.military_strength - before
        assert gain_with_sheet == self._baseline_gain(DecreeType.PERSONNEL)

    def test_no_player_sheet_safe(self):
        """角色卡缺失（{}）→ 安全跳过修正，效果等于基准。"""
        assert self._baseline_gain(DecreeType.RECRUIT_TROOPS) is not None
        base = create_initial_state()
        gain = self._military_gain(base, DecreeType.RECRUIT_TROOPS)
        assert gain == self._baseline_gain(DecreeType.RECRUIT_TROOPS)


# ── 史实威胁清除（e2e 平衡修复：事件效果支持枚举直设）──────

class TestThreatClearing:
    def test_script_effect_clears_region_threat(self):
        """state_effects 支持 region.*.threat 字符串直设（转枚举，历史不可逆）。"""
        from api.helpers import apply_state_effects
        from models.enums import RegionThreat
        state = create_initial_state()
        region = next(r for r in state.regions if r.name == "镇江")
        assert region.threat is RegionThreat.WU   # 镇江守军为张士诚吴军
        apply_state_effects(state, {"region.镇江.threat": "none"})
        assert region.threat is RegionThreat.NONE

    def test_script_choice_parses_string_effect(self):
        """事件加载器接受 str 效果值（region.*.threat/control 直设）。"""
        from engine.scripts import _parse_choice
        choice = _parse_choice({
            "label": "克胜镇江",
            "description": "收复京畿重镇",
            "state_effects": {"region.镇江.threat": "none", "global.military_morale": 5},
        }, ctx="test")
        assert choice.state_effects["region.镇江.threat"] == "none"
        assert choice.state_effects["global.military_morale"] == 5

    def test_decree_request_accepts_string_effect(self):
        """/decree 请求体放宽：choice 的 state_effects 原样回传（含 str 威胁清除）不 422。"""
        req = DecreeRequest(state_effects={"region.镇江.threat": "none"})
        assert req.state_effects == {"region.镇江.threat": "none"}

    def test_freeform_script_resolution_clears_threat(self):
        """端到端：自由文本解析镇江事件 choice 0 → 威胁清除落库，无 500（回归步骤7 修复）。"""
        api_state._provider = _fake_provider()
        state = create_initial_state()
        state.time = GameTime(year=1356, month=10, era_name="至正", era_year=16)
        inject_script_events(state)
        api_state._state = state
        assert any(e.script_id == "zhenjiang-campaign-1356-10" for e in state.active_events)

        result = asyncio.run(api_routes.execute_decree(DecreeRequest(
            source_script_id="zhenjiang-campaign-1356-10",
            free_text="乘胜东进，徐图常州",
        )))

        zhenjiang = next(r for r in result["state"]["regions"] if r["name"] == "镇江")
        assert zhenjiang["threat"] == RegionThreat.NONE.value
        assert "zhenjiang-campaign-1356-10" in result["state"]["resolved_script_ids"]
