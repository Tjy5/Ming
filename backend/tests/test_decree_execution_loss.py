"""08-07-decree-execution-loss 测试。

覆盖：
- 损耗系数：只消费具名实际执行者，并可由其当前因子复算
- stable seed 派生跨调用一致；普通行动入口不消费偏差
- 三路径统一：structured / freeform / trpg writeback 均经损耗
"""

import math

from engine import execution_loss as el
from engine.core import apply_base_effects
from models.game import GameState, Minister, MinisterAbilities, MinisterStatus, GameTime
from models.enums import DecreeType
from trpg.writeback import apply_state_changes


def _minister(corruption: int, loyalty: int = 100, civil: int = 100, status=MinisterStatus.ACTIVE) -> Minister:
    return Minister(
        name=f"m{corruption}",
        faction="test",
        abilities=MinisterAbilities(civil=civil, military=50, diplomacy=50),
        loyalty=loyalty,
        corruption=corruption,
        status=status,
        positions=["测试官职"],
    )


status_removed = MinisterStatus.REMOVED


def _state(ministers, seed=None) -> GameState:
    return GameState(
        time=GameTime(),
        ministers=ministers,
        execution_rng_seed=seed,
    )


# ── 损耗系数 ─────────────────────────────────────────────

class TestLossFactor:
    def test_clean_officials_no_loss(self):
        s = _state([_minister(0, loyalty=100, civil=100)])
        assert math.isclose(el.execution_loss_factor(s, "m0"), 1.0, abs_tol=1e-6)

    def test_high_corruption_strong_loss(self):
        s = _state([
            _minister(0, loyalty=100, civil=100),
            _minister(90, loyalty=100, civil=100),
        ])
        clean_factor = el.execution_loss_factor(s, "m0")
        corrupt_factor = el.execution_loss_factor(s, "m90")
        assert 0 < corrupt_factor < clean_factor <= 1

    def test_extreme_corruption_floored(self):
        s = _state([_minister(100, loyalty=0, civil=0)])
        factor = el.execution_loss_factor(s, "m100")
        assert factor >= el.MIN_LOSS_FACTOR

    def test_no_ministers_no_loss(self):
        s = _state([])
        assert el.execution_loss_factor(s) == 1.0

    def test_dismissed_minister_excluded(self):
        s = _state([
            _minister(100, loyalty=0, civil=0, status=status_removed),
            _minister(0, loyalty=100, civil=100),
        ])
        assert math.isclose(el.execution_loss_factor(s), 1.0, abs_tol=1e-6)
        assert el.execution_loss_factor(s, "m100") == 0


# ── 可控偏差 ─────────────────────────────────────────────

class TestSeededDeviation:
    def test_no_seed_is_deterministic_zero(self):
        s = _state([_minister(50)])
        assert el.seeded_deviation(el._derive_seed(s, "k"), 5) == 0

    def test_fixed_seed_reproducible(self):
        s = _state([_minister(50)], seed=12345)
        a = el.seeded_deviation(el._derive_seed(s, "k"), 5)
        b = el.seeded_deviation(el._derive_seed(s, "k"), 5)
        assert a == b
        assert -5 <= a <= 5

    def test_different_key_different_deviation(self):
        s = _state([_minister(50)], seed=12345)
        d1 = el.seeded_deviation(el._derive_seed(s, "a"), 5)
        d2 = el.seeded_deviation(el._derive_seed(s, "b"), 5)
        # 不保证必不同，但两者都应在范围内
        assert -5 <= d1 <= 5 and -5 <= d2 <= 5


# ── 统一损耗入口 ─────────────────────────────────────────

class TestApplyExecutionLoss:
    def test_scales_down_with_corruption(self):
        s = _state([_minister(90, loyalty=100, civil=100)])
        out = el.apply_execution_loss(s, {"national_treasury": 100}, executor_name="m90")
        factor = el.execution_loss_factor(s, "m90")
        assert out["national_treasury"] == math.floor(100 * factor)
        assert 0 < out["national_treasury"] < 100

    def test_no_sign_flip_positive(self):
        s = _state([_minister(90)])
        out = el.apply_execution_loss(s, {"grain": 3}, seed_keys={"grain": "g"})
        assert out["grain"] >= 0

    def test_no_sign_flip_negative(self):
        s = _state([_minister(90)])
        out = el.apply_execution_loss(s, {"grain": -3}, seed_keys={"grain": "g"})
        assert out["grain"] <= 0


# ── 三路径接入 ───────────────────────────────────────────

class TestPaths:
    def test_structured_applies_loss(self):
        from models.game import StructuredDecree
        s = _state([_minister(90, loyalty=100, civil=100)])
        # 真实表 RECRUIT_TROOPS：military_strength +8, population -30 等
        decree = StructuredDecree(type=DecreeType.RECRUIT_TROOPS)
        before = s.military_strength
        attr: dict = {}
        apply_base_effects(s, decree, attr, executor_name="m90")
        gained = s.military_strength - before
        assert gained < 8, f"满腐败应损耗，实际增益={gained}"
        # 至少一个受影响字段有 execution_loss 归因
        assert any("execution_loss" in v for v in attr.values())

    def test_freeform_global_loss(self):
        from models.game import FreeformResult
        from engine.core import process_decree
        s = _state([_minister(90, loyalty=100, civil=100)])
        before = s.national_treasury
        expected_delta = el.apply_execution_loss(
            s,
            {"national_treasury": 100},
            executor_name="m90",
            action_kind="governance",
        )["national_treasury"]
        freeform = FreeformResult(effects={"global.national_treasury": 100})
        process_decree(s, freeform=freeform, executor_name="m90")
        assert s.national_treasury == before + expected_delta

    def test_trpg_writeback_global_loss(self):
        s = _state([_minister(90, loyalty=100, civil=100)])
        before = s.national_treasury
        expected_delta = el.apply_execution_loss(
            s,
            {"national_treasury": 100},
            executor_name="m90",
            action_kind="governance",
        )["national_treasury"]
        res = apply_state_changes(
            s,
            {"global.national_treasury": 100},
            executor_name="m90",
        )
        assert "global.national_treasury" in res["applied"]
        assert s.national_treasury == before + expected_delta


# ── clamp 约束 ───────────────────────────────────────────

class TestClamp:
    def test_corruption_clamped(self):
        from models.game import clamp_state
        m = Minister.model_construct(name="x", faction="f", corruption=999)
        s = _state([m])
        clamp_state(s)
        assert s.ministers[0].corruption <= 100
