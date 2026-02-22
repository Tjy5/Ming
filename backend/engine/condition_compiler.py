from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from models.game import GameState


ConditionFn = Callable[["GameState"], bool]

_ALLOWED_STATE_FIELDS = {
    "national_treasury",
    "imperial_treasury",
    "grain",
    "population",
    "military_strength",
    "civil_morale",
    "military_morale",
    "court_prestige",
}

_ALLOWED_REGION_FIELDS = {
    "stability",
    "garrison",
    "civil_morale",
    "rebellion_risk",
    "disaster_level",
    "tax_collected",
    "tax_rate",
}

_ALLOWED_FACTION_FIELDS = {
    "satisfaction",
    "influence",
    "rebellion_risk",
}


def _expect_dict(spec: Any, *, ctx: str) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError(f"{ctx} must be an object")
    return spec


def _expect_str(spec: dict[str, Any], key: str, *, ctx: str) -> str:
    value = spec.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{ctx}.{key} must be a non-empty string")
    return value.strip()


def _expect_int(spec: dict[str, Any], key: str, *, ctx: str) -> int:
    value = spec.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{ctx}.{key} must be an integer")
    return value


def _load_script_helpers():
    # Keep the source of truth in scripts.py so DSL and script runtime share identical semantics.
    from .scripts import (
        _faction_field,
        _minister_active,
        _minister_alive,
        _minister_removed,
        _region_field,
        _state_field,
    )

    return (
        _minister_alive,
        _minister_removed,
        _minister_active,
        _region_field,
        _faction_field,
        _state_field,
    )


def compile_condition(spec: dict[str, Any] | None) -> ConditionFn | None:
    if spec is None:
        return None

    (
        minister_alive,
        minister_removed,
        minister_active,
        region_field,
        faction_field,
        state_field,
    ) = _load_script_helpers()

    node = _expect_dict(spec, ctx="condition")
    node_type = _expect_str(node, "type", ctx="condition")

    if node_type == "minister_alive":
        name = _expect_str(node, "name", ctx="condition")
        return lambda s, n=name: minister_alive(s, n)

    if node_type == "minister_removed":
        name = _expect_str(node, "name", ctx="condition")
        return lambda s, n=name: minister_removed(s, n)

    if node_type == "minister_active":
        name = _expect_str(node, "name", ctx="condition")
        return lambda s, n=name: minister_active(s, n)

    if node_type == "script_resolved":
        script_id = _expect_str(node, "script_id", ctx="condition")
        return lambda s, sid=script_id: sid in s.resolved_script_ids

    if node_type == "state_field_lt":
        field = _expect_str(node, "field", ctx="condition")
        if field not in _ALLOWED_STATE_FIELDS:
            raise ValueError(f"condition.field '{field}' is not supported for state_field_lt")
        value = _expect_int(node, "value", ctx="condition")
        return lambda s, f=field, v=value: (state_field(s, f) is not None) and (state_field(s, f) < v)

    if node_type == "state_field_gt":
        field = _expect_str(node, "field", ctx="condition")
        if field not in _ALLOWED_STATE_FIELDS:
            raise ValueError(f"condition.field '{field}' is not supported for state_field_gt")
        value = _expect_int(node, "value", ctx="condition")
        return lambda s, f=field, v=value: (state_field(s, f) is not None) and (state_field(s, f) > v)

    if node_type == "region_field_lt":
        region = _expect_str(node, "region", ctx="condition")
        field = _expect_str(node, "field", ctx="condition")
        if field not in _ALLOWED_REGION_FIELDS:
            raise ValueError(f"condition.field '{field}' is not supported for region_field_lt")
        value = _expect_int(node, "value", ctx="condition")
        return lambda s, r=region, f=field, v=value: (region_field(s, r, f) is not None) and (region_field(s, r, f) < v)

    if node_type == "region_field_gt":
        region = _expect_str(node, "region", ctx="condition")
        field = _expect_str(node, "field", ctx="condition")
        if field not in _ALLOWED_REGION_FIELDS:
            raise ValueError(f"condition.field '{field}' is not supported for region_field_gt")
        value = _expect_int(node, "value", ctx="condition")
        return lambda s, r=region, f=field, v=value: (region_field(s, r, f) is not None) and (region_field(s, r, f) > v)

    if node_type == "faction_field_lt":
        faction = _expect_str(node, "faction", ctx="condition")
        field = _expect_str(node, "field", ctx="condition")
        if field not in _ALLOWED_FACTION_FIELDS:
            raise ValueError(f"condition.field '{field}' is not supported for faction_field_lt")
        value = _expect_int(node, "value", ctx="condition")
        return lambda s, fac=faction, f=field, v=value: (faction_field(s, fac, f) is not None) and (faction_field(s, fac, f) < v)

    if node_type == "faction_field_gt":
        faction = _expect_str(node, "faction", ctx="condition")
        field = _expect_str(node, "field", ctx="condition")
        if field not in _ALLOWED_FACTION_FIELDS:
            raise ValueError(f"condition.field '{field}' is not supported for faction_field_gt")
        value = _expect_int(node, "value", ctx="condition")
        return lambda s, fac=faction, f=field, v=value: (faction_field(s, fac, f) is not None) and (faction_field(s, fac, f) > v)

    if node_type == "and":
        raw_conditions = node.get("conditions")
        if not isinstance(raw_conditions, list) or not raw_conditions:
            raise ValueError("condition.conditions must be a non-empty array for and")
        compiled = [
            compile_condition(_expect_dict(child, ctx=f"condition.conditions[{idx}]"))
            for idx, child in enumerate(raw_conditions)
        ]
        return lambda s, fns=compiled: all(fn(s) for fn in fns if fn is not None)

    raise ValueError(f"Unsupported condition type: {node_type}")
