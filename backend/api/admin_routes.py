from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from data.data_manager import get_data_manager
from db.saves import DB_PATH
from engine.condition_compiler import compile_condition
from models.game import ErrorResponse, Minister, StructuredDecree
from models.positions import POSITION_REGISTRY, get_position_info, can_appoint

from .admin_auth import require_admin


admin_router = APIRouter(prefix="/api/admin")

_SCRIPT_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _raise_http(
    status: int,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> None:
    raise HTTPException(
        status,
        detail=ErrorResponse(
            error_code=code,
            message=message,
            details=details,
        ).model_dump(),
    )


def _split_positions_text(value: str) -> list[str]:
    tokens = [value]
    for delimiter in ("兼", "、", "，", ","):
        next_tokens: list[str] = []
        for token in tokens:
            next_tokens.extend(token.split(delimiter))
        tokens = next_tokens
    return [token.strip() for token in tokens if token.strip()]


def _normalize_positions(raw: Any, *, ctx: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError(f"{ctx}.positions must be an array")

    normalized: list[str] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, str):
            raise ValueError(f"{ctx}.positions[{idx}] must be a string")
        for token in _split_positions_text(item):
            info = get_position_info(token)
            if info is None:
                raise ValueError(f"{ctx}.positions has invalid position: {token}")
            canonical = token.strip()
            if token.strip() not in POSITION_REGISTRY:
                # get_position_info already resolved alias; recover canonical name
                for name, position_info in POSITION_REGISTRY.items():
                    if token.strip() == name or token.strip() in position_info.aliases:
                        canonical = name
                        break
            if canonical not in normalized:
                normalized.append(canonical)
    return normalized


def _minister_from_raw(raw: Any, *, ctx: str) -> Minister:
    if not isinstance(raw, dict):
        raise ValueError(f"{ctx} must be an object")
    payload = dict(raw)
    if "positions" not in payload and "position" in payload:
        legacy = payload.get("position")
        payload["positions"] = [legacy] if isinstance(legacy, str) and legacy.strip() else []
    payload["positions"] = _normalize_positions(payload.get("positions", []), ctx=ctx)
    return Minister.model_validate(payload)


def _validate_minister_collection(ministers: list[Minister], *, strict: bool = True) -> None:
    names = [m.name for m in ministers]
    if len(names) != len(set(names)):
        raise ValueError("Minister names must be unique")

    unique_holder: dict[str, str] = {}
    for minister in ministers:
        for position in minister.positions:
            if get_position_info(position) is None:
                raise ValueError(f"{minister.name} has invalid position: {position}")
            info = get_position_info(position)
            if info is not None and info.unique:
                current = unique_holder.get(position)
                if current is not None and current != minister.name:
                    if strict:
                        raise ValueError(f"Unique position '{position}' is held by both {current} and {minister.name}")
                    else:
                        import logging
                        logging.getLogger("admin").warning(
                            "Unique position '%s' held by both %s and %s",
                            position, current, minister.name,
                        )
                unique_holder[position] = minister.name


def _validate_minister_constraints(minister: Minister) -> None:
    for position in minister.positions:
        if not can_appoint(minister.is_eunuch, minister.faction, minister.personality_tags, position):
            raise ValueError(
                f"{minister.name} cannot hold position {position} under historical constraints"
            )


def _load_ministers() -> list[Minister]:
    manager = get_data_manager()
    raw_ministers = manager.get_ministers()
    ministers = [
        _minister_from_raw(item, ctx=f"ministers[{idx}]")
        for idx, item in enumerate(raw_ministers)
    ]
    _validate_minister_collection(ministers, strict=False)
    return ministers


def _save_ministers(ministers: list[Minister]) -> None:
    _validate_minister_collection(ministers, strict=False)
    payload = [minister.model_dump(mode="json") for minister in ministers]
    get_data_manager().write_ministers(payload)


class MinisterCreate(Minister):
    pass


class MinisterUpdate(Minister):
    pass


class AdminScriptChoice(BaseModel):
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    decrees: list[StructuredDecree] = Field(default_factory=list)
    loyalty_effects: list[tuple[str, int]] = Field(default_factory=list)
    state_effects: dict[str, int] = Field(default_factory=dict)


class AdminScriptEvent(BaseModel):
    script_id: str = Field(min_length=1)
    trigger_year: int = Field(ge=1328, le=1368)
    trigger_month: int = Field(ge=1, le=12)
    title: str = Field(min_length=1)
    rich_description: str
    historical_hint: str = Field(min_length=1)
    is_blocking: bool = False
    condition: dict[str, Any] | None = None
    choices: list[AdminScriptChoice] = Field(min_length=1)


def _validate_event_payload(raw: Any, *, ctx: str) -> dict[str, Any]:
    try:
        event = AdminScriptEvent.model_validate(raw)
    except Exception as exc:
        raise ValueError(f"{ctx} validation failed: {exc}") from exc

    if not _SCRIPT_ID_RE.fullmatch(event.script_id):
        raise ValueError(f"{ctx}.script_id must match pattern ^[a-z0-9]+(?:-[a-z0-9]+)*$")

    try:
        compile_condition(event.condition)
    except ValueError as exc:
        raise ValueError(f"{ctx}.condition is invalid: {exc}") from exc

    payload = event.model_dump(mode="json")
    return payload


def _load_events() -> dict[str, dict[str, Any]]:
    return get_data_manager().get_events()


def _condition_mentions_minister(condition: Any, minister_name: str) -> bool:
    if not isinstance(condition, dict):
        return False
    node_type = condition.get("type")
    if node_type in {"minister_alive", "minister_removed", "minister_active"}:
        return condition.get("name") == minister_name
    if node_type == "and":
        children = condition.get("conditions")
        if isinstance(children, list):
            return any(_condition_mentions_minister(child, minister_name) for child in children)
    return False


def _event_references_minister(event: dict[str, Any], minister_name: str) -> bool:
    if _condition_mentions_minister(event.get("condition"), minister_name):
        return True

    for choice in event.get("choices", []):
        if not isinstance(choice, dict):
            continue

        for decree in choice.get("decrees", []):
            if isinstance(decree, dict) and decree.get("target") == minister_name:
                return True

        for loyalty in choice.get("loyalty_effects", []):
            if isinstance(loyalty, (list, tuple)) and len(loyalty) == 2 and loyalty[0] == minister_name:
                return True

        state_effects = choice.get("state_effects", {})
        if isinstance(state_effects, dict):
            prefix = f"minister.{minister_name}."
            if any(isinstance(key, str) and key.startswith(prefix) for key in state_effects):
                return True

    return False


def _event_is_active_in_saves(script_id: str) -> list[int]:
    save_ids: list[int] = []
    with sqlite3.connect(str(DB_PATH), timeout=5) as conn:
        rows = conn.execute("SELECT id, state_json FROM saves").fetchall()
    for save_id, state_json in rows:
        try:
            payload = json.loads(state_json)
        except Exception:
            continue
        active_events = payload.get("active_events", [])
        if not isinstance(active_events, list):
            continue
        if any(isinstance(item, dict) and item.get("script_id") == script_id for item in active_events):
            save_ids.append(int(save_id))
    return save_ids


def _positions_snapshot_equal(snapshot: Any, current: dict[str, dict[str, Any]]) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if set(snapshot.keys()) != set(current.keys()):
        return False
    for name, expected in current.items():
        got = snapshot.get(name)
        if not isinstance(got, dict):
            return False
        if got.get("category") != expected["category"]:
            return False
        if got.get("weight") != expected["weight"]:
            return False
        if got.get("unique") != expected["unique"]:
            return False
        got_aliases = got.get("aliases", [])
        if not isinstance(got_aliases, list):
            return False
        if sorted(got_aliases) != sorted(expected["aliases"]):
            return False
    return True


def _validate_import_payload(payload: dict[str, Any]) -> tuple[list[Minister], list[dict[str, Any]]]:
    raw_ministers = payload.get("ministers")
    if not isinstance(raw_ministers, list):
        _raise_http(422, "invalid_import", "ministers 必须为数组")

    raw_events = payload.get("events")
    if isinstance(raw_events, dict):
        event_items = list(raw_events.values())
    elif isinstance(raw_events, list):
        event_items = raw_events
    else:
        _raise_http(422, "invalid_import", "events 必须为数组或对象映射")

    positions_snapshot = payload.get("positions")
    current_positions = get_data_manager().get_positions()
    if positions_snapshot is not None and not _positions_snapshot_equal(positions_snapshot, current_positions):
        _raise_http(422, "invalid_import", "positions 快照与服务器只读官职表不一致")

    try:
        ministers = [
            _minister_from_raw(item, ctx=f"ministers[{idx}]")
            for idx, item in enumerate(raw_ministers)
        ]
        _validate_minister_collection(ministers, strict=False)
    except ValueError as exc:
        _raise_http(422, "invalid_import_ministers", str(exc))

    validated_events: list[dict[str, Any]] = []
    seen_script_ids: set[str] = set()
    for idx, item in enumerate(event_items):
        try:
            event = _validate_event_payload(item, ctx=f"events[{idx}]")
        except ValueError as exc:
            _raise_http(422, "invalid_import_events", str(exc))
        script_id = event["script_id"]
        if script_id in seen_script_ids:
            _raise_http(422, "invalid_import_events", f"重复 script_id: {script_id}")
        seen_script_ids.add(script_id)
        validated_events.append(event)

    return ministers, validated_events


def _as_payload_dict(payload: Any, *, ctx: str) -> dict[str, Any]:
    if isinstance(payload, BaseModel):
        dumped = payload.model_dump(mode="json")
        if not isinstance(dumped, dict):
            raise ValueError(f"{ctx} must serialize to an object")
        return dumped
    if isinstance(payload, dict):
        return payload
    raise ValueError(f"{ctx} must be an object")


@admin_router.get("/verify")
async def verify_admin(_: None = Depends(require_admin)):
    return {"ok": True}


@admin_router.get("/ministers")
async def admin_get_ministers(_: None = Depends(require_admin)):
    ministers = _load_ministers()
    return [minister.model_dump(mode="json") for minister in ministers]


@admin_router.get("/ministers/{name}")
async def admin_get_minister(name: str, _: None = Depends(require_admin)):
    ministers = _load_ministers()
    minister = next((item for item in ministers if item.name == name), None)
    if minister is None:
        _raise_http(404, "minister_not_found", f"大臣 {name} 不存在")
    return minister.model_dump(mode="json")


@admin_router.post("/ministers")
async def admin_create_minister(payload: MinisterCreate, _: None = Depends(require_admin)):
    ministers = _load_ministers()
    try:
        candidate = _minister_from_raw(_as_payload_dict(payload, ctx="payload"), ctx="payload")
        _validate_minister_constraints(candidate)
        if any(item.name == candidate.name for item in ministers):
            _raise_http(409, "minister_exists", f"大臣 {candidate.name} 已存在")
        ministers.append(candidate)
        _save_ministers(ministers)
    except HTTPException:
        raise
    except ValueError as exc:
        _raise_http(422, "invalid_minister", str(exc))
    return candidate.model_dump(mode="json")


@admin_router.put("/ministers/{name}")
async def admin_update_minister(name: str, payload: MinisterUpdate, _: None = Depends(require_admin)):
    ministers = _load_ministers()
    index = next((idx for idx, item in enumerate(ministers) if item.name == name), None)
    if index is None:
        _raise_http(404, "minister_not_found", f"大臣 {name} 不存在")

    try:
        updated = _minister_from_raw(_as_payload_dict(payload, ctx="payload"), ctx="payload")
        _validate_minister_constraints(updated)
        if updated.name != name and any(item.name == updated.name for item in ministers):
            _raise_http(409, "minister_exists", f"大臣 {updated.name} 已存在")
        ministers[index] = updated
        _save_ministers(ministers)
    except HTTPException:
        raise
    except ValueError as exc:
        _raise_http(422, "invalid_minister", str(exc))
    return updated.model_dump(mode="json")


@admin_router.delete("/ministers/{name}")
async def admin_delete_minister(name: str, _: None = Depends(require_admin)):
    ministers = _load_ministers()
    index = next((idx for idx, item in enumerate(ministers) if item.name == name), None)
    if index is None:
        _raise_http(404, "minister_not_found", f"大臣 {name} 不存在")

    events = _load_events()
    referenced_by = [
        script_id
        for script_id, event in events.items()
        if _event_references_minister(event, name)
    ]
    if referenced_by:
        _raise_http(
            409,
            "minister_referenced_by_event",
            f"大臣 {name} 被剧情事件引用，无法删除",
            details={"script_ids": referenced_by},
        )

    removed = ministers.pop(index)
    _save_ministers(ministers)
    return {"ok": True, "name": removed.name}


@admin_router.get("/events")
async def admin_get_events(_: None = Depends(require_admin)):
    events = list(_load_events().values())
    events.sort(key=lambda item: (item.get("trigger_year", 0), item.get("trigger_month", 0), item.get("script_id", "")))
    return events


@admin_router.get("/events/{script_id}")
async def admin_get_event(script_id: str, _: None = Depends(require_admin)):
    events = _load_events()
    event = events.get(script_id)
    if event is None:
        _raise_http(404, "event_not_found", f"事件 {script_id} 不存在")
    return event


@admin_router.post("/events")
async def admin_create_event(payload: dict[str, Any], _: None = Depends(require_admin)):
    events = _load_events()
    try:
        event = _validate_event_payload(payload, ctx="payload")
    except ValueError as exc:
        _raise_http(422, "invalid_event", str(exc))

    script_id = event["script_id"]
    if script_id in events:
        _raise_http(409, "event_exists", f"事件 {script_id} 已存在")

    get_data_manager().write_event(event)
    return event


@admin_router.put("/events/{script_id}")
async def admin_update_event(script_id: str, payload: dict[str, Any], _: None = Depends(require_admin)):
    events = _load_events()
    if script_id not in events:
        _raise_http(404, "event_not_found", f"事件 {script_id} 不存在")

    try:
        event = _validate_event_payload(payload, ctx="payload")
    except ValueError as exc:
        _raise_http(422, "invalid_event", str(exc))

    if event["script_id"] != script_id:
        _raise_http(422, "invalid_event", "script_id 不可在更新时修改")

    get_data_manager().write_event(event)
    return event


@admin_router.delete("/events/{script_id}")
async def admin_delete_event(script_id: str, _: None = Depends(require_admin)):
    events = _load_events()
    if script_id not in events:
        _raise_http(404, "event_not_found", f"事件 {script_id} 不存在")

    active_save_ids = _event_is_active_in_saves(script_id)
    if active_save_ids:
        _raise_http(
            409,
            "event_active_in_saves",
            f"事件 {script_id} 仍在存档中处于激活状态，无法删除",
            details={"save_ids": active_save_ids[:20]},
        )

    deleted = get_data_manager().delete_event(script_id)
    if not deleted:
        _raise_http(404, "event_not_found", f"事件 {script_id} 不存在")
    return {"ok": True, "script_id": script_id}


@admin_router.get("/positions")
async def admin_get_positions(_: None = Depends(require_admin)):
    ministers = _load_ministers()
    holders: dict[str, list[str]] = {}
    for minister in ministers:
        for position in minister.positions:
            holders.setdefault(position, []).append(minister.name)

    result: list[dict[str, Any]] = []
    for name, info in POSITION_REGISTRY.items():
        result.append(
            {
                "name": name,
                "category": info.category.value,
                "weight": info.weight,
                "unique": info.unique,
                "aliases": list(info.aliases),
                "holders": holders.get(name, []),
            }
        )
    result.sort(key=lambda item: (item["category"], -item["weight"], item["name"]))
    return result


@admin_router.get("/export")
async def admin_export(_: None = Depends(require_admin)):
    bundle = get_data_manager().export_bundle()
    bundle["meta"] = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
    }
    return bundle


@admin_router.post("/import/validate")
async def admin_import_validate(payload: dict[str, Any] = Body(...), _: None = Depends(require_admin)):
    ministers, validated_events = _validate_import_payload(payload)
    return {
        "ok": True,
        "ministers_count": len(ministers),
        "events_count": len(validated_events),
    }


@admin_router.post("/import")
async def admin_import(payload: dict[str, Any] = Body(...), _: None = Depends(require_admin)):
    ministers, validated_events = _validate_import_payload(payload)

    try:
        get_data_manager().import_bundle(
            ministers=[minister.model_dump(mode="json") for minister in ministers],
            events=validated_events,
        )
    except ValueError as exc:
        _raise_http(422, "invalid_import", str(exc))
    except Exception as exc:
        _raise_http(500, "import_failed", f"导入失败: {exc}")

    return {
        "ok": True,
        "ministers_count": len(ministers),
        "events_count": len(validated_events),
    }
