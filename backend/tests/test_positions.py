"""Unit tests for Position Registry (元末明初版)."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from models.positions import (
    POSITION_REGISTRY,
    PositionCategory,
    PositionInfo,
    calculate_position_weight,
    get_position_info,
    resolve_position,
    can_appoint,
    is_eunuch_position,
    is_unique_position,
)


# ── Test data constants ─────────────────────────────────────────────

# SECONDARY positions that are legitimately non-unique (multiple holders in reality)
SECONDARY_NON_UNIQUE: set[str] = {
    "元帅", "总管", "判官", "参军", "万户", "镇抚", "千户", "检校",
}

ALL_CANONICAL_NAMES = tuple(POSITION_REGISTRY.keys())
ALL_ALIASES = tuple(
    alias for info in POSITION_REGISTRY.values() for alias in info.aliases
)

ALIAS_PAIRS = tuple(
    (alias, canonical)
    for canonical, info in POSITION_REGISTRY.items()
    for alias in info.aliases
)


@pytest.mark.parametrize("category", [PositionCategory.SECONDARY, PositionCategory.NOBLE])
def test_secondary_and_noble_positions_non_unique(category):
    """Non-CORE positions should be unique unless listed in exception set."""
    exceptions = SECONDARY_NON_UNIQUE if category == PositionCategory.SECONDARY else set()
    for name, info in POSITION_REGISTRY.items():
        if info.category == category and name not in exceptions:
            assert info.unique is True, f"{name} ({category.value}) should be unique"


def test_eunuch_positions_are_unique():
    """EUNUCH positions must be unique."""
    for name, info in POSITION_REGISTRY.items():
        if info.category == PositionCategory.EUNUCH:
            assert info.unique is True, f"{name} should be unique"


# ── Weight Bounds ─────────────────────────────────────────────────────


def test_all_position_weights_in_range():
    """All position weights must be in [0, 200] range."""
    for name, info in POSITION_REGISTRY.items():
        assert 0 <= info.weight <= 200, f"{name} weight {info.weight} out of range"


# ── resolve_position ───────────────────────────────────────────────────


@given(alias_pair=st.sampled_from(ALIAS_PAIRS) if ALIAS_PAIRS else st.none())
@settings(max_examples=50)
def test_resolve_position_returns_canonical_for_alias(alias_pair):
    """resolve_position should return canonical name for aliases."""
    if alias_pair is None:
        pytest.skip("No aliases defined")
    alias, canonical = alias_pair
    assert resolve_position(alias) == canonical


@given(name=st.sampled_from(ALL_CANONICAL_NAMES))
@settings(max_examples=50)
def test_resolve_position_returns_same_for_canonical(name):
    """resolve_position should return same name for canonical names."""
    assert resolve_position(name) == name


def test_resolve_position_returns_none_for_unknown():
    """resolve_position should return None for unknown positions."""
    assert resolve_position("不存在的官职XYZ") is None
    assert resolve_position("") is None
    assert resolve_position("   ") is None


# ── get_position_info ─────────────────────────────────────────────────


@given(name=st.sampled_from(ALL_CANONICAL_NAMES))
@settings(max_examples=50)
def test_get_position_info_returns_info_for_valid(name):
    """get_position_info should return PositionInfo for valid names."""
    info = get_position_info(name)
    assert isinstance(info, PositionInfo)
    assert info == POSITION_REGISTRY[name]


def test_get_position_info_returns_none_for_unknown():
    """get_position_info should return None for unknown names."""
    assert get_position_info("不存在的官职XYZ") is None


# ── calculate_position_weight ─────────────────────────────────────────


def test_calculate_position_weight_empty_list():
    """calculate_position_weight should return 0 for empty list."""
    assert calculate_position_weight([]) == 0


def test_calculate_position_weight_single_position():
    """calculate_position_weight should return correct weight for single position."""
    assert calculate_position_weight(["左丞相"]) == 120
    assert calculate_position_weight(["参知政事"]) == 90


def test_calculate_position_weight_cumulative():
    """calculate_position_weight should return cumulative weight for multiple positions."""
    # 平章政事 (110) + 同知都督 (90)
    weight = calculate_position_weight(["平章政事", "同知都督"])
    assert weight == 200


def test_calculate_position_weight_unknown_contributes_zero():
    """calculate_position_weight should contribute 0 for unknown positions."""
    weight = calculate_position_weight(["左丞相", "不存在的官职"])
    assert weight == 120


# ── Registry Completeness ────────────────────────────────────────────


def test_registry_has_core_positions():
    """Registry must contain all expected CORE positions."""
    expected_core = {
        "左丞相", "右丞相", "平章政事", "左丞", "右丞", "参知政事",
        "大都督", "同知都督", "御史大夫", "治书侍御史",
    }
    actual_core = {
        name for name, info in POSITION_REGISTRY.items()
        if info.category == PositionCategory.CORE
    }
    assert expected_core <= actual_core, f"Missing CORE positions: {expected_core - actual_core}"


def test_registry_has_military_positions():
    """Registry must contain non-unique military positions."""
    expected = {"元帅", "总管", "判官", "参军", "万户", "镇抚", "千户"}
    actual = {
        name for name, info in POSITION_REGISTRY.items()
        if info.category == PositionCategory.SECONDARY and not info.unique
    }
    assert expected <= actual


def test_registry_has_eunuch_positions():
    """Registry must contain EUNUCH positions."""
    eunuch_positions = [
        name for name, info in POSITION_REGISTRY.items()
        if info.category == PositionCategory.EUNUCH
    ]
    assert "宣徽使" in eunuch_positions
    assert "内史监令" in eunuch_positions


# ── is_eunuch_position ─────────────────────────────────────────────────


def test_is_eunuch_position_true_for_eunuch():
    """is_eunuch_position should return True for EUNUCH category positions."""
    assert is_eunuch_position("宣徽使") is True
    assert is_eunuch_position("内史监令") is True


def test_is_eunuch_position_false_for_non_eunuch():
    """is_eunuch_position should return False for non-EUNUCH positions."""
    assert is_eunuch_position("左丞相") is False
    assert is_eunuch_position("元帅") is False
    assert is_eunuch_position("太师") is False


def test_is_eunuch_position_false_for_unknown():
    """is_eunuch_position should return False for unknown positions."""
    assert is_eunuch_position("不存在的官职") is False


# ── is_unique_position ─────────────────────────────────────────────────


def test_is_unique_position_true_for_core():
    """is_unique_position should return True for unique CORE positions."""
    assert is_unique_position("左丞相") is True
    assert is_unique_position("参知政事") is True
    assert is_unique_position("大都督") is True


def test_is_unique_position_for_secondary():
    """SECONDARY文职唯一，军职非唯一。"""
    assert is_unique_position("太史令") is True
    assert is_unique_position("经历") is True
    assert is_unique_position("元帅") is False
    assert is_unique_position("总管") is False


def test_is_unique_position_for_noble():
    """All NOBLE positions are unique."""
    assert is_unique_position("吴国公") is True
    assert is_unique_position("太师") is True


def test_is_unique_position_true_for_eunuch():
    """is_unique_position should return True for EUNUCH positions."""
    assert is_unique_position("宣徽使") is True


def test_is_unique_position_false_for_unknown():
    """is_unique_position should return False for unknown positions."""
    assert is_unique_position("不存在的官职") is False


# ── can_appoint ───────────────────────────────────────────────────────


def test_can_appoint_eunuch_to_eunuch_position():
    """Eunuch ministers can be appointed to EUNUCH positions."""
    assert can_appoint(minister_eunuch=True, minister_faction="元廷", minister_tags=[], position="宣徽使") is True
    assert can_appoint(minister_eunuch=True, minister_faction="元廷", minister_tags=[], position="内史监令") is True


def test_can_appoint_eunuch_to_non_eunuch_position():
    """Eunuch ministers cannot be appointed to non-EUNUCH positions."""
    assert can_appoint(minister_eunuch=True, minister_faction="元廷", minister_tags=[], position="左丞相") is False
    assert can_appoint(minister_eunuch=True, minister_faction="元廷", minister_tags=[], position="元帅") is False
    assert can_appoint(minister_eunuch=True, minister_faction="元廷", minister_tags=["勋贵"], position="太师") is False


def test_can_appoint_non_eunuch_to_eunuch_position():
    """Non-eunuch ministers cannot be appointed to EUNUCH positions."""
    assert can_appoint(minister_eunuch=False, minister_faction="幕府文臣", minister_tags=[], position="宣徽使") is False


def test_can_appoint_non_eunuch_to_non_eunuch_position():
    """Non-eunuch ministers can be appointed to non-EUNUCH positions."""
    assert can_appoint(minister_eunuch=False, minister_faction="幕府文臣", minister_tags=[], position="左丞相") is True
    assert can_appoint(minister_eunuch=False, minister_faction="淮西勋将", minister_tags=[], position="元帅") is True
    assert can_appoint(minister_eunuch=False, minister_faction="元廷", minister_tags=["勋贵"], position="太师") is True


def test_can_appoint_unknown_position():
    """can_appoint should return False for unknown positions."""
    assert can_appoint(minister_eunuch=True, minister_faction="元廷", minister_tags=[], position="不存在的官职") is False
    assert can_appoint(minister_eunuch=False, minister_faction="幕府文臣", minister_tags=[], position="不存在的官职") is False


def test_can_appoint_noble_constraint():
    """Nobles can only hold noble positions, and only nobles can hold noble positions."""
    # Noble minister trying to hold civil pos -> False
    assert can_appoint(minister_eunuch=False, minister_faction="汉政权", minister_tags=["勋贵"], position="左丞相") is False
    # Civil minister trying to hold noble pos -> False
    assert can_appoint(minister_eunuch=False, minister_faction="幕府文臣", minister_tags=[], position="太尉") is False
    # Noble minister holding noble pos -> True
    assert can_appoint(minister_eunuch=False, minister_faction="汉政权", minister_tags=["勋贵"], position="太尉") is True


# ── Integration Tests: Game State ─────────────────────────────────────


def test_eunuch_ministers_only_have_eunuch_positions():
    """Ministers with is_eunuch=True should only have EUNUCH category positions."""
    from models.game import create_initial_state

    state = create_initial_state()
    eunuch_ministers = [m for m in state.ministers if m.is_eunuch]

    for m in eunuch_ministers:
        for pos in m.positions:
            info = get_position_info(pos)
            assert info is not None, f"Unknown position '{pos}' for eunuch minister {m.name}"
            assert info.category == PositionCategory.EUNUCH, \
                f"Eunuch minister {m.name} has non-EUNUCH position '{pos}' (category: {info.category})"


def test_non_eunuch_ministers_no_eunuch_positions():
    """Ministers with is_eunuch=False should NOT have EUNUCH category positions."""
    from models.game import create_initial_state

    state = create_initial_state()
    non_eunuch_ministers = [m for m in state.ministers if not m.is_eunuch]

    for m in non_eunuch_ministers:
        for pos in m.positions:
            info = get_position_info(pos)
            if info is None:
                continue  # Skip unknown positions
            assert info.category != PositionCategory.EUNUCH, \
                f"Non-eunuch minister {m.name} has EUNUCH position '{pos}'"


def test_unique_positions_single_holder_in_roster():
    """Unique positions in the initial roster should have at most one holder."""
    from models.game import INITIAL_MINISTERS

    holder: dict[str, str] = {}
    for m in INITIAL_MINISTERS:
        for pos in m.positions:
            info = get_position_info(pos)
            if info is None or not info.unique:
                continue
            assert pos not in holder or holder[pos] == m.name, \
                f"Unique position '{pos}' held by both {holder.get(pos)} and {m.name}"
            holder[pos] = m.name


def test_initial_state_minister_position_coverage():
    """At least 80% of ministers should have positions in initial state."""
    from models.game import create_initial_state

    state = create_initial_state()
    total = len(state.ministers)
    with_positions = len([m for m in state.ministers if m.positions])

    coverage = with_positions / total if total > 0 else 0
    assert coverage >= 0.80, f"Position coverage is {coverage:.1%}, expected >= 80%"
    print(f"Position coverage: {with_positions}/{total} ({coverage:.1%})")
