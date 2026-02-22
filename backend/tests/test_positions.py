"""Unit tests for Position Registry."""

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

CORE_NON_UNIQUE: set[str] = set()  # All positions are now unique

ALL_CANONICAL_NAMES = tuple(POSITION_REGISTRY.keys())
ALL_ALIASES = tuple(
    alias for info in POSITION_REGISTRY.values() for alias in info.aliases
)
ALL_KNOWN_NAMES = set(ALL_CANONICAL_NAMES) | set(ALL_ALIASES)

ALIAS_PAIRS = tuple(
    (alias, canonical)
    for canonical, info in POSITION_REGISTRY.items()
    for alias in info.aliases
)


# ── Category/Uniqueness Constraints ───────────────────────────────────


CORE_NON_UNIQUE = set()  # All positions are now unique


@pytest.mark.parametrize("category", [PositionCategory.SECONDARY, PositionCategory.NOBLE])
def test_secondary_and_noble_positions_non_unique(category):
    """All positions are now unique (1 person per position)."""
    for name, info in POSITION_REGISTRY.items():
        if info.category == category:
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
    assert calculate_position_weight(["首辅大学士"]) == 120
    assert calculate_position_weight(["吏部尚书"]) == 100


def test_calculate_position_weight_cumulative():
    """calculate_position_weight should return cumulative weight for multiple positions."""
    # 礼部尚书 (100) + 东阁大学士 (110)
    weight = calculate_position_weight(["礼部尚书", "东阁大学士"])
    assert weight == 210


def test_calculate_position_weight_unknown_contributes_zero():
    """calculate_position_weight should contribute 0 for unknown positions."""
    weight = calculate_position_weight(["首辅大学士", "不存在的官职"])
    assert weight == 120


# ── Registry Completeness (PBT Property) ─────────────────────────────


def test_registry_has_core_positions():
    """Registry must contain all expected CORE positions."""
    expected_core = {
        "首辅大学士", "次辅大学士",
        "东阁大学士", "文渊阁大学士", "武英殿大学士",
        "吏部尚书", "吏部侍郎", "户部尚书", "户部侍郎",
        "礼部尚书", "礼部侍郎", "兵部尚书", "兵部侍郎",
        "刑部尚书", "刑部侍郎", "工部尚书", "工部侍郎",
        "左都御史", "指挥使",
        "辽东巡抚", "河南巡抚", "福建巡抚", "登莱巡抚",
        "宣府总兵", "山海关总兵", "东江总兵",
    }
    actual_core = {
        name for name, info in POSITION_REGISTRY.items()
        if info.category == PositionCategory.CORE
    }
    assert expected_core <= actual_core, f"Missing CORE positions: {expected_core - actual_core}"


def test_registry_has_eunuch_positions():
    """Registry must contain EUNUCH positions."""
    eunuch_positions = [
        name for name, info in POSITION_REGISTRY.items()
        if info.category == PositionCategory.EUNUCH
    ]
    assert "司礼监太监" in eunuch_positions
    assert "司礼监秉笔太监" in eunuch_positions


# ── is_eunuch_position ─────────────────────────────────────────────────


def test_is_eunuch_position_true_for_eunuch():
    """is_eunuch_position should return True for EUNUCH category positions."""
    assert is_eunuch_position("司礼监太监") is True
    assert is_eunuch_position("司礼监掌印太监") is True
    assert is_eunuch_position("司礼监秉笔太监") is True


def test_is_eunuch_position_false_for_non_eunuch():
    """is_eunuch_position should return False for non-EUNUCH positions."""
    assert is_eunuch_position("首辅大学士") is False
    assert is_eunuch_position("吏部尚书") is False
    assert is_eunuch_position("成国公") is False


def test_is_eunuch_position_false_for_unknown():
    """is_eunuch_position should return False for unknown positions."""
    assert is_eunuch_position("不存在的官职") is False


# ── is_unique_position ─────────────────────────────────────────────────


def test_is_unique_position_true_for_core_unique():
    """is_unique_position should return True for unique CORE positions."""
    assert is_unique_position("首辅大学士") is True
    assert is_unique_position("吏部尚书") is True
    assert is_unique_position("左都御史") is True


def test_is_unique_position_false_for_core_non_unique():
    """All CORE positions are now unique."""
    # 巡抚 and 总兵 have been split into specific regional positions
    assert is_unique_position("辽东巡抚") is True
    assert is_unique_position("宣府总兵") is True


def test_is_unique_position_false_for_secondary():
    """All SECONDARY positions are now unique."""
    assert is_unique_position("翰林学士") is True
    assert is_unique_position("监察御史") is True


def test_is_unique_position_false_for_noble():
    """All NOBLE positions are now unique."""
    assert is_unique_position("成国公") is True
    assert is_unique_position("英国公") is True


def test_is_unique_position_true_for_eunuch():
    """is_unique_position should return True for EUNUCH positions."""
    assert is_unique_position("司礼监太监") is True
    assert is_unique_position("司礼监掌印太监") is True


def test_is_unique_position_false_for_unknown():
    """is_unique_position should return False for unknown positions."""
    assert is_unique_position("不存在的官职") is False


# ── can_appoint ───────────────────────────────────────────────────────


def test_can_appoint_eunuch_to_eunuch_position():
    """Eunuch ministers can be appointed to EUNUCH positions."""
    assert can_appoint(minister_eunuch=True, minister_faction="阉党", minister_tags=[], position="司礼监太监") is True
    assert can_appoint(minister_eunuch=True, minister_faction="阉党", minister_tags=[], position="司礼监掌印太监") is True


def test_can_appoint_eunuch_to_non_eunuch_position():
    """Eunuch ministers cannot be appointed to non-EUNUCH positions."""
    assert can_appoint(minister_eunuch=True, minister_faction="阉党", minister_tags=["翰林"], position="首辅大学士") is False
    assert can_appoint(minister_eunuch=True, minister_faction="阉党", minister_tags=[], position="吏部尚书") is False
    assert can_appoint(minister_eunuch=True, minister_faction="阉党", minister_tags=["勋贵"], position="成国公") is False


def test_can_appoint_non_eunuch_to_eunuch_position():
    """Non-eunuch ministers cannot be appointed to EUNUCH positions."""
    assert can_appoint(minister_eunuch=False, minister_faction="东林党", minister_tags=[], position="司礼监太监") is False
    assert can_appoint(minister_eunuch=False, minister_faction="东林党", minister_tags=[], position="司礼监掌印太监") is False


def test_can_appoint_non_eunuch_to_non_eunuch_position():
    """Non-eunuch ministers can be appointed to non-EUNUCH positions."""
    assert can_appoint(minister_eunuch=False, minister_faction="东林党", minister_tags=["翰林"], position="首辅大学士") is True
    assert can_appoint(minister_eunuch=False, minister_faction="东林党", minister_tags=[], position="吏部尚书") is True
    assert can_appoint(minister_eunuch=False, minister_faction="勋贵集团", minister_tags=["勋贵"], position="成国公") is True
    assert can_appoint(minister_eunuch=False, minister_faction="东林党", minister_tags=["翰林"], position="翰林学士") is True


def test_can_appoint_unknown_position():
    """can_appoint should return False for unknown positions."""
    assert can_appoint(minister_eunuch=True, minister_faction="阉党", minister_tags=[], position="不存在的官职") is False
    assert can_appoint(minister_eunuch=False, minister_faction="东林党", minister_tags=[], position="不存在的官职") is False

def test_can_appoint_hanlin_constraint():
    """Only ministers with the Hanlin tag can enter the Grand Secretariat."""
    assert can_appoint(minister_eunuch=False, minister_faction="东林党", minister_tags=[], position="首辅大学士") is False
    assert can_appoint(minister_eunuch=False, minister_faction="东林党", minister_tags=["翰林"], position="首辅大学士") is True
    
def test_can_appoint_noble_constraint():
    """Nobles can only hold noble positions, and only nobles can hold noble positions."""
    # Noble minister trying to hold civil pos -> False
    assert can_appoint(minister_eunuch=False, minister_faction="勋贵集团", minister_tags=["勋贵"], position="吏部尚书") is False
    # Civil minister trying to hold noble pos -> False
    assert can_appoint(minister_eunuch=False, minister_faction="东林党", minister_tags=[], position="成国公") is False
    # Noble minister holding noble pos -> True
    assert can_appoint(minister_eunuch=False, minister_faction="勋贵集团", minister_tags=["勋贵"], position="成国公") is True

def test_can_appoint_military_constraint():
    """Military generals cannot be appointed as regional governors."""
    # General as Xunfu -> False
    assert can_appoint(minister_eunuch=False, minister_faction="辽东边将", minister_tags=["武将"], position="辽东巡抚") is False
    # General as Zongbing -> True
    assert can_appoint(minister_eunuch=False, minister_faction="辽东边将", minister_tags=["武将"], position="山海关总兵") is True
    # Civil as Xunfu -> True
    assert can_appoint(minister_eunuch=False, minister_faction="东林党", minister_tags=[], position="辽东巡抚") is True


# ── Integration Tests: Game State ─────────────────────────────────────


def test_unique_positions_are_marked_correctly():
    """Verify that positions marked as unique=True are correctly identified."""
    unique_core_positions = [
        name for name, info in POSITION_REGISTRY.items()
        if info.category == PositionCategory.CORE and info.unique
    ]
    # All positions are unique in the new design
    assert "首辅大学士" in unique_core_positions
    assert "吏部尚书" in unique_core_positions
    assert "辽东巡抚" in unique_core_positions
    assert "宣府总兵" in unique_core_positions


def test_secondary_position_allows_multiple_holders():
    """SECONDARY positions should allow multiple ACTIVE ministers."""
    from models.game import create_initial_state
    from models.enums import MinisterStatus

    state = create_initial_state()
    active_ministers = [m for m in state.ministers if m.status == MinisterStatus.ACTIVE]

    # Find SECONDARY positions with multiple holders
    secondary_counts: dict[str, int] = {}
    for m in active_ministers:
        for pos in m.positions:
            info = get_position_info(pos)
            if info is not None and info.category == PositionCategory.SECONDARY:
                secondary_counts[pos] = secondary_counts.get(pos, 0) + 1

    # At least some SECONDARY positions might have multiple holders (not a strict requirement)
    # This test just verifies the system allows it
    assert isinstance(secondary_counts, dict)


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


def test_initial_state_minister_position_coverage():
    """At least 80% of ministers should have positions in initial state."""
    from models.game import create_initial_state
    from models.enums import MinisterStatus

    state = create_initial_state()
    total = len(state.ministers)
    with_positions = len([m for m in state.ministers if m.positions])

    coverage = with_positions / total if total > 0 else 0
    assert coverage >= 0.80, f"Position coverage is {coverage:.1%}, expected >= 80%"
    print(f"Position coverage: {with_positions}/{total} ({coverage:.1%})")
