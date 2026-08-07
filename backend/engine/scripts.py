from __future__ import annotations

import copy
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, cast

if TYPE_CHECKING:
    from models.game import GameState

from models.enums import DecreeType, PersonnelAction
from models.game import StructuredDecree

@dataclass
class ScriptChoice:
    label: str
    description: str
    decrees: list[StructuredDecree] = field(default_factory=list)
    loyalty_effects: list[tuple[str, int]] = field(default_factory=list)
    # 数值增量（int）或枚举字段直设（str，如 region.*.threat 史实威胁清除，
    # 阶段D 平衡修复——见 api/helpers.apply_state_effects）
    state_effects: dict[str, int | str] = field(default_factory=dict)


@dataclass
class ScriptEvent:
    script_id: str
    trigger_year: int
    trigger_month: int
    title: str
    rich_description: str
    choices: list[ScriptChoice]
    historical_hint: str = ""
    is_blocking: bool = False
    condition_spec: dict | None = None
    condition: Callable[[GameState], bool] | None = None


SCRIPT_EVENTS_DIR = Path(__file__).resolve().parents[1] / "data" / "yuanming" / "events"

# ── Script Registry ─────────────────────────────────────

SCRIPT_REGISTRY: dict[str, ScriptEvent] = {}
_REGISTRY_LOCK = threading.RLock()
_REGISTRY_SIGNATURE: tuple[tuple[str, int, int], ...] | None = None


def _find_minister(state: GameState, name: str):
    return next((m for m in state.ministers if m.name == name), None)


def _minister_active(state: GameState, name: str) -> bool:
    minister = _find_minister(state, name)
    return minister is not None and minister.status.value == "active"


def _minister_removed(state: GameState, name: str) -> bool:
    minister = _find_minister(state, name)
    return minister is not None and minister.status.value == "removed"


def _minister_alive(state: GameState, name: str) -> bool:
    return not _minister_removed(state, name)


def _region_field(state: GameState, region_name: str, field: str) -> int | float | None:
    region = next((r for r in state.regions if r.name == region_name), None)
    if region is None:
        return None
    return getattr(region, field, None)


def _faction_field(state: GameState, faction_name: str, field: str) -> int | float | None:
    faction = next((f for f in state.factions if f.name == faction_name), None)
    if faction is None:
        return None
    return getattr(faction, field, None)


def _state_field(state: GameState, field: str) -> int | float | None:
    return getattr(state, field, None)


def _register(evt: ScriptEvent) -> None:
    if not evt.script_id:
        raise ValueError("script_id must be non-empty")
    if evt.script_id in SCRIPT_REGISTRY:
        raise ValueError(f"duplicate script_id: {evt.script_id}")
    if not 1328 <= evt.trigger_year <= 1368:
        raise ValueError(f"trigger_year out of range: {evt.trigger_year}")
    if not 1 <= evt.trigger_month <= 12:
        raise ValueError(f"trigger_month out of range: {evt.trigger_month}")
    if not evt.choices:
        raise ValueError(f"script {evt.script_id} must have at least one choice")
    if not isinstance(evt.historical_hint, str) or not evt.historical_hint.strip():
        raise ValueError(f"script {evt.script_id} must have non-empty historical_hint")
    SCRIPT_REGISTRY[evt.script_id] = evt


def _to_signature() -> tuple[tuple[str, int, int], ...]:
    files = sorted(SCRIPT_EVENTS_DIR.glob("*.json"))
    signature: list[tuple[str, int, int]] = []
    for file in files:
        stat = file.stat()
        signature.append((file.name, stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def _parse_decree(raw: object, *, ctx: str) -> StructuredDecree:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} must be an object")

    raw_type = raw.get("type")
    if not isinstance(raw_type, str) or not raw_type.strip():
        raise ValueError(f"{ctx}.type must be a non-empty string")
    normalized_type = raw_type.strip().lower()
    try:
        decree_type = DecreeType(normalized_type)
    except ValueError as exc:
        raise ValueError(f"{ctx}.type is invalid: {raw_type}") from exc

    target = raw.get("target")
    if target is not None and not isinstance(target, str):
        raise ValueError(f"{ctx}.target must be a string when provided")

    sub_action_raw = raw.get("sub_action")
    sub_action = None
    if sub_action_raw is not None:
        if not isinstance(sub_action_raw, str):
            raise ValueError(f"{ctx}.sub_action must be a string when provided")
        try:
            sub_action = PersonnelAction(sub_action_raw.strip().lower())
        except ValueError as exc:
            raise ValueError(f"{ctx}.sub_action is invalid: {sub_action_raw}") from exc

    parameters_raw = raw.get("parameters")
    parameters: dict | None = None
    if parameters_raw is not None:
        if not isinstance(parameters_raw, dict):
            raise ValueError(f"{ctx}.parameters must be an object when provided")
        parameters = cast(dict, copy.deepcopy(parameters_raw))

    return StructuredDecree(
        type=decree_type,
        target=target,
        sub_action=sub_action,
        parameters=parameters,
    )


def _parse_choice(raw: object, *, ctx: str) -> ScriptChoice:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} must be an object")

    label = raw.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"{ctx}.label must be a non-empty string")

    description_raw = raw.get("description", "")
    if not isinstance(description_raw, str):
        raise ValueError(f"{ctx}.description must be a string")

    decrees_raw = raw.get("decrees", [])
    if not isinstance(decrees_raw, list):
        raise ValueError(f"{ctx}.decrees must be an array")
    decrees = [
        _parse_decree(item, ctx=f"{ctx}.decrees[{idx}]")
        for idx, item in enumerate(decrees_raw)
    ]

    loyalty_effects_raw = raw.get("loyalty_effects", [])
    if not isinstance(loyalty_effects_raw, list):
        raise ValueError(f"{ctx}.loyalty_effects must be an array")
    loyalty_effects: list[tuple[str, int]] = []
    for idx, pair in enumerate(loyalty_effects_raw):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f"{ctx}.loyalty_effects[{idx}] must be [name, delta]")
        name, delta = pair[0], pair[1]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{ctx}.loyalty_effects[{idx}][0] must be a non-empty string")
        if not isinstance(delta, int):
            raise ValueError(f"{ctx}.loyalty_effects[{idx}][1] must be an integer")
        loyalty_effects.append((name.strip(), delta))

    state_effects_raw = raw.get("state_effects", {})
    if not isinstance(state_effects_raw, dict):
        raise ValueError(f"{ctx}.state_effects must be an object")
    state_effects: dict[str, int | str] = {}
    for key, value in state_effects_raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"{ctx}.state_effects key must be a non-empty string")
        # int = 增量；str = 枚举字段直设（region.*.threat/control，史实威胁清除）
        if not isinstance(value, (int, str)):
            raise ValueError(f"{ctx}.state_effects['{key}'] must be an integer or string")
        state_effects[key] = value

    return ScriptChoice(
        label=label.strip(),
        description=description_raw,
        decrees=decrees,
        loyalty_effects=loyalty_effects,
        state_effects=state_effects,
    )


def _parse_event_payload(raw: object, *, source: str) -> ScriptEvent:
    from .condition_compiler import compile_condition

    if not isinstance(raw, dict):
        raise ValueError(f"{source} must be a JSON object")

    script_id = raw.get("script_id")
    if not isinstance(script_id, str) or not script_id.strip():
        raise ValueError(f"{source}.script_id must be a non-empty string")
    script_id = script_id.strip()

    trigger_year = raw.get("trigger_year")
    if not isinstance(trigger_year, int):
        raise ValueError(f"{source}.trigger_year must be an integer")

    trigger_month = raw.get("trigger_month")
    if not isinstance(trigger_month, int):
        raise ValueError(f"{source}.trigger_month must be an integer")

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"{source}.title must be a non-empty string")

    rich_description = raw.get("rich_description")
    if not isinstance(rich_description, str):
        raise ValueError(f"{source}.rich_description must be a string")

    historical_hint = raw.get("historical_hint")
    if not isinstance(historical_hint, str):
        raise ValueError(f"{source}.historical_hint must be a string")

    is_blocking_raw = raw.get("is_blocking", False)
    if not isinstance(is_blocking_raw, bool):
        raise ValueError(f"{source}.is_blocking must be a boolean")

    condition_spec = raw.get("condition")
    if condition_spec is not None and not isinstance(condition_spec, dict):
        raise ValueError(f"{source}.condition must be an object or null")
    condition = compile_condition(cast(dict | None, condition_spec))

    choices_raw = raw.get("choices")
    if not isinstance(choices_raw, list):
        raise ValueError(f"{source}.choices must be an array")
    choices = [
        _parse_choice(choice, ctx=f"{source}.choices[{idx}]")
        for idx, choice in enumerate(choices_raw)
    ]

    return ScriptEvent(
        script_id=script_id,
        trigger_year=trigger_year,
        trigger_month=trigger_month,
        title=title.strip(),
        rich_description=rich_description,
        choices=choices,
        historical_hint=historical_hint,
        is_blocking=is_blocking_raw,
        condition_spec=cast(dict | None, copy.deepcopy(condition_spec)),
        condition=condition,
    )


def _load_event_file(path: Path) -> ScriptEvent:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    return _parse_event_payload(payload, source=str(path))


def reload_script_registry(*, force: bool = False) -> bool:
    global _REGISTRY_SIGNATURE
    with _REGISTRY_LOCK:
        signature = _to_signature()
        if not force and _REGISTRY_SIGNATURE == signature:
            return False

        old_registry = dict(SCRIPT_REGISTRY)
        old_signature = _REGISTRY_SIGNATURE

        try:
            files = sorted(SCRIPT_EVENTS_DIR.glob("*.json"))
            SCRIPT_REGISTRY.clear()
            for path in files:
                _register(_load_event_file(path))
            _REGISTRY_SIGNATURE = signature
            return True
        except Exception:
            SCRIPT_REGISTRY.clear()
            SCRIPT_REGISTRY.update(old_registry)
            _REGISTRY_SIGNATURE = old_signature
            raise


def get_scripts_for_time(year: int, month: int) -> list[ScriptEvent]:
    reload_script_registry(force=False)
    return [
        event for event in SCRIPT_REGISTRY.values()
        if event.trigger_year == year and event.trigger_month == month
    ]


def script_event_to_dict(event: ScriptEvent) -> dict:
    return {
        "script_id": event.script_id,
        "trigger_year": event.trigger_year,
        "trigger_month": event.trigger_month,
        "title": event.title,
        "is_blocking": event.is_blocking,
        "rich_description": event.rich_description,
        "historical_hint": event.historical_hint,
        "condition": copy.deepcopy(event.condition_spec),
        "choices": [
            {
                "label": choice.label,
                "description": choice.description,
                "decrees": [
                    decree.model_dump(mode="json", exclude_none=True)
                    for decree in choice.decrees
                ],
                "loyalty_effects": [[name, delta] for name, delta in choice.loyalty_effects],
                "state_effects": dict(choice.state_effects),
            }
            for choice in event.choices
        ],
    }


reload_script_registry(force=True)
