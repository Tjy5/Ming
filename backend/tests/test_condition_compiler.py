from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import engine.condition_compiler as condition_compiler
from engine.condition_compiler import compile_condition
from models.enums import MinisterStatus
from models.game import create_initial_state


def test_compile_condition_none_returns_none():
    assert compile_condition(None) is None


def test_compile_condition_minister_alive():
    state = create_initial_state()
    fn = compile_condition({"type": "minister_alive", "name": "杨宪"})
    assert fn is not None
    assert fn(state) is True

    target = next(m for m in state.ministers if m.name == "杨宪")
    target.status = MinisterStatus.REMOVED
    assert fn(state) is False


def test_compile_condition_and_with_state_field_gt():
    state = create_initial_state()
    # 新档开局 1328-10 徐达尚未入仕（NOT_YET_ENTERED），显式置为在朝以测条件语义
    next(m for m in state.ministers if m.name == "徐达").status = MinisterStatus.ACTIVE
    state.military_strength = 25
    fn = compile_condition(
        {
            "type": "and",
            "conditions": [
                {"type": "minister_active", "name": "徐达"},
                {"type": "state_field_gt", "field": "military_strength", "value": 20},
            ],
        }
    )
    assert fn is not None
    assert fn(state) is True

    state.military_strength = 15
    assert fn(state) is False


def test_compile_condition_rejects_unknown_type():
    with pytest.raises(ValueError, match="Unsupported condition type"):
        compile_condition({"type": "unknown_type"})


def test_compile_condition_rejects_invalid_state_field():
    with pytest.raises(ValueError, match="is not supported for state_field_gt"):
        compile_condition({"type": "state_field_gt", "field": "unknown", "value": 1})


_name_strategy = st.text(
    alphabet=st.characters(
        min_codepoint=ord("a"),
        max_codepoint=ord("z"),
    ),
    min_size=1,
    max_size=12,
)
_script_id_strategy = st.from_regex(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", fullmatch=True)
_state_field_strategy = st.sampled_from(sorted(condition_compiler._ALLOWED_STATE_FIELDS))
_region_field_strategy = st.sampled_from(sorted(condition_compiler._ALLOWED_REGION_FIELDS))
_faction_field_strategy = st.sampled_from(sorted(condition_compiler._ALLOWED_FACTION_FIELDS))
_value_strategy = st.integers(min_value=-999, max_value=999)

_leaf_condition_strategy = st.one_of(
    st.builds(lambda name: {"type": "minister_alive", "name": name}, _name_strategy),
    st.builds(lambda name: {"type": "minister_removed", "name": name}, _name_strategy),
    st.builds(lambda name: {"type": "minister_active", "name": name}, _name_strategy),
    st.builds(lambda script_id: {"type": "script_resolved", "script_id": script_id}, _script_id_strategy),
    st.builds(
        lambda field, value: {"type": "state_field_lt", "field": field, "value": value},
        _state_field_strategy,
        _value_strategy,
    ),
    st.builds(
        lambda field, value: {"type": "state_field_gt", "field": field, "value": value},
        _state_field_strategy,
        _value_strategy,
    ),
    st.builds(
        lambda region, field, value: {"type": "region_field_lt", "region": region, "field": field, "value": value},
        _name_strategy,
        _region_field_strategy,
        _value_strategy,
    ),
    st.builds(
        lambda region, field, value: {"type": "region_field_gt", "region": region, "field": field, "value": value},
        _name_strategy,
        _region_field_strategy,
        _value_strategy,
    ),
    st.builds(
        lambda faction, field, value: {"type": "faction_field_lt", "faction": faction, "field": field, "value": value},
        _name_strategy,
        _faction_field_strategy,
        _value_strategy,
    ),
    st.builds(
        lambda faction, field, value: {"type": "faction_field_gt", "faction": faction, "field": field, "value": value},
        _name_strategy,
        _faction_field_strategy,
        _value_strategy,
    ),
)

_valid_condition_strategy = st.recursive(
    _leaf_condition_strategy,
    lambda children: st.builds(
        lambda conditions: {"type": "and", "conditions": conditions},
        st.lists(children, min_size=1, max_size=3),
    ),
    max_leaves=10,
)


@given(spec=_valid_condition_strategy)
@settings(max_examples=120)
def test_compile_condition_accepts_valid_generated_dsl(spec):
    state = create_initial_state()
    fn = compile_condition(spec)
    assert fn is not None
    assert isinstance(fn(state), bool)
