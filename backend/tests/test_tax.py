import math
from models.game import Region, GameState, Faction, clamp_state
from models.enums import TaxContribution
from engine.core import recalc_tax_collected


def _make_region(name="test", stability=50, tax_rate=0.5,
                 tax_contribution=TaxContribution.MEDIUM, **kw) -> Region:
    return Region(name=name, stability=stability, garrison=10000,
                  tax_contribution=tax_contribution, tax_rate=tax_rate, **kw)


def _make_state(regions: list[Region]) -> GameState:
    return GameState(regions=regions, factions=[
        Faction(name="test", satisfaction=50, influence=50, rebellion_risk=10),
    ])


class TestRecalcTaxCollected:
    def test_basic_formula(self):
        r = _make_region(stability=80, tax_rate=0.5,
                         tax_contribution=TaxContribution.MEDIUM)
        state = _make_state([r])
        recalc_tax_collected(state, 1.0)
        # floor(220 * 0.5 * 0.8 * 1.0) = floor(14.0) = 14
        assert r.tax_collected == math.floor(220 * 0.5 * (80 / 100) * 1.0)

    def test_high_contribution(self):
        r = _make_region(stability=100, tax_rate=0.8,
                         tax_contribution=TaxContribution.HIGH)
        state = _make_state([r])
        recalc_tax_collected(state, 1.0)
        assert r.tax_collected == math.floor(360 * 0.8 * 1.0 * 1.0)

    def test_low_contribution(self):
        r = _make_region(stability=60, tax_rate=0.3,
                         tax_contribution=TaxContribution.LOW)
        state = _make_state([r])
        recalc_tax_collected(state, 1.0)
        assert r.tax_collected == math.floor(120 * 0.3 * 0.6 * 1.0)

    def test_tax_increase_modifier(self):
        r = _make_region(stability=50, tax_rate=0.5,
                         tax_contribution=TaxContribution.MEDIUM)
        state = _make_state([r])
        recalc_tax_collected(state, 1.15)
        assert r.tax_collected == math.floor(220 * 0.5 * 0.5 * 1.15)

    def test_tax_decrease_modifier(self):
        r = _make_region(stability=50, tax_rate=0.5,
                         tax_contribution=TaxContribution.MEDIUM)
        state = _make_state([r])
        recalc_tax_collected(state, 0.85)
        assert r.tax_collected == math.floor(220 * 0.5 * 0.5 * 0.85)

    def test_zero_stability(self):
        r = _make_region(stability=0, tax_rate=0.5)
        state = _make_state([r])
        recalc_tax_collected(state, 1.0)
        assert r.tax_collected == 0

    def test_zero_tax_rate(self):
        r = _make_region(stability=80, tax_rate=0.0)
        state = _make_state([r])
        recalc_tax_collected(state, 1.0)
        assert r.tax_collected == 0

    def test_multiple_regions(self):
        r1 = _make_region("a", stability=100, tax_rate=1.0,
                          tax_contribution=TaxContribution.HIGH)
        r2 = _make_region("b", stability=50, tax_rate=0.3,
                          tax_contribution=TaxContribution.LOW)
        state = _make_state([r1, r2])
        recalc_tax_collected(state, 1.0)
        assert r1.tax_collected == math.floor(360 * 1.0 * 1.0 * 1.0)
        assert r2.tax_collected == math.floor(120 * 0.3 * 0.5 * 1.0)


class TestTaxRateClampAndPrecision:
    def test_clamp_above_1(self):
        r = _make_region(tax_rate=1.0)
        r.tax_rate = 1.2  # bypass validator for test
        state = _make_state([r])
        clamp_state(state)
        assert r.tax_rate == 1.0

    def test_clamp_below_0(self):
        r = _make_region(tax_rate=0.0)
        r.tax_rate = -0.1
        state = _make_state([r])
        clamp_state(state)
        assert r.tax_rate == 0.0

    def test_round_precision(self):
        r = _make_region(tax_rate=0.5)
        r.tax_rate = 0.1 + 0.1 + 0.1  # floating point: 0.30000000000000004
        state = _make_state([r])
        clamp_state(state)
        assert r.tax_rate == 0.3

    def test_round_after_drift(self):
        r = _make_region(tax_rate=0.5)
        # simulate multiple small decrements
        for _ in range(7):
            r.tax_rate -= 0.02
        state = _make_state([r])
        clamp_state(state)
        assert r.tax_rate == round(0.5 - 0.02 * 7, 2)

    def test_recalc_rounds_before_calculation(self):
        r = _make_region(stability=100, tax_rate=0.5,
                         tax_contribution=TaxContribution.MEDIUM)
        r.tax_rate = 0.1 + 0.1 + 0.1  # 0.30000000000000004
        state = _make_state([r])
        recalc_tax_collected(state, 1.0)
        # recalc should round tax_rate first: 0.3, then floor(35*0.3*1.0*1.0)=10
        assert r.tax_rate == 0.3
        assert r.tax_collected == math.floor(220 * 0.3 * 1.0 * 1.0)

    def test_tax_collected_non_negative_after_clamp(self):
        r = _make_region(stability=0, tax_rate=0.0)
        state = _make_state([r])
        recalc_tax_collected(state, 1.0)
        clamp_state(state)
        assert r.tax_collected >= 0
