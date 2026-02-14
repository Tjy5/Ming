from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models.game import (
    GameState, StructuredDecree, DecreeResponse, HistoryEntry,
    ErrorResponse, create_initial_state,
)
from engine.core import process_decree, check_preconditions, validate_target
from ai.provider import PARSE_ERROR_TYPE_UNAVAILABLE, get_provider
from db.saves import (
    init_db, save_game, load_game, list_saves, delete_save, auto_save,
    SaveNotFoundError, CorruptSaveError, StorageError,
)

router = APIRouter(prefix="/api")

# ── In-memory state ─────────────────────────────────────

_state: GameState | None = None
_lock = asyncio.Lock()
_provider = None


def _get_state() -> GameState:
    global _state
    if _state is None:
        _state = create_initial_state()
    return _state


def _get_provider():
    global _provider
    if _provider is None:
        _provider = get_provider()
    return _provider


def startup():
    init_db()


# ── Request / Response models ───────────────────────────

class DecreeRequest(BaseModel):
    decrees: list[StructuredDecree]
    source_script_id: str | None = None


class ParseRequest(BaseModel):
    text: str


class SaveRequest(BaseModel):
    name: str | None = None


# ── 6.1 POST /api/game/new ─────────────────────────────

@router.post("/game/new")
async def new_game():
    global _state
    _state = create_initial_state()
    return _state.model_dump()


# ── 6.2 POST /api/decree ───────────────────────────────

@router.post("/decree")
async def execute_decree(req: DecreeRequest):
    if _lock.locked():
        raise HTTPException(409, detail=ErrorResponse(
            error_code="decree_in_progress",
            message="正在处理上一道政令，请稍候",
        ).model_dump())

    async with _lock:
        state = _get_state()
        provider = _get_provider()

        if not req.decrees and not req.source_script_id:
            raise HTTPException(422, detail=ErrorResponse(
                error_code="invalid_decree",
                message="至少需要一道政令",
            ).model_dump())

        last_response: dict | None = None

        for decree in req.decrees:
            reason = check_preconditions(state, decree)
            if reason:
                narrative = await provider.rejection_narrative(decree, reason)
                raise HTTPException(422, detail=ErrorResponse(
                    error_code="precondition_failed",
                    message=reason,
                    details={"ai_narrative": narrative},
                ).model_dump())

            target_err = validate_target(decree)
            if target_err:
                raise HTTPException(422, detail=ErrorResponse(
                    error_code="invalid_decree",
                    message=target_err,
                ).model_dump())

            delta, attribution, triggered, game_over = process_decree(state, decree)

            narrative = await provider.generate_narrative(
                attribution, state, triggered, decree,
            )

            state.history_log.append(HistoryEntry(
                year=state.time.year, month=state.time.month,
                decree_type=decree.type.value,
                decree_desc=decree.target or "",
                delta=delta, narrative=narrative,
            ))

            if state.decree_count % 5 == 0:
                auto_save(state)

            last_response = DecreeResponse(
                state=state, delta=delta, attribution=attribution,
                narrative=narrative, newly_triggered_events=triggered,
                game_time=state.time, game_over=game_over,
            ).model_dump()

            if game_over:
                break

        if req.source_script_id:
            before_count = len(state.active_events)
            state.active_events = [
                e for e in state.active_events
                if e.script_id != req.source_script_id
            ]
            if len(state.active_events) != before_count:
                state.resolved_script_ids.add(req.source_script_id)

        if last_response is None:
            # empty decrees (e.g. script "wait" option) — still advance turn
            delta, attribution, triggered, game_over = process_decree(state)
            narrative = "陛下暂且按兵不动，静观时局变化。"
            state.history_log.append(HistoryEntry(
                year=state.time.year, month=state.time.month,
                decree_type="wait", decree_desc="",
                delta=delta, narrative=narrative,
            ))
            if state.decree_count % 5 == 0:
                auto_save(state)
            last_response = DecreeResponse(
                state=state, delta=delta, attribution=attribution,
                narrative=narrative, newly_triggered_events=triggered,
                game_time=state.time, game_over=game_over,
            ).model_dump()

        # refresh state in response after script cleanup
        last_response["state"] = state.model_dump()
        return last_response


# ── 6.3 POST /api/decree/parse ─────────────────────────

@router.post("/decree/parse")
async def parse_decree(req: ParseRequest):
    provider = _get_provider()
    result = await provider.parse_free_input(req.text, _get_state())
    if isinstance(result, dict) and "error" in result:
        is_unavailable = result.get("error_type") == PARSE_ERROR_TYPE_UNAVAILABLE
        raise HTTPException(503 if is_unavailable else 422, detail=ErrorResponse(
            error_code="parse_unavailable" if is_unavailable else "parse_error",
            message=result["error"],
        ).model_dump())
    return [d.model_dump() for d in result]


# ── 6.4 GET /api/state ─────────────────────────────────

@router.get("/state")
async def get_state():
    state = _get_state()
    data = state.model_dump()
    total = len(data["history_log"])
    data["history_log"] = data["history_log"][-20:]
    data["history_total_count"] = total
    return data


# ── 6.5 GET /api/history ───────────────────────────────

@router.get("/history")
async def get_history(offset: int = 0, limit: int = 20):
    state = _get_state()
    total = len(state.history_log)
    entries = state.history_log[offset:offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "entries": [e.model_dump() for e in entries],
    }


# ── 6.6 POST /api/save ─────────────────────────────────

@router.post("/save")
async def save(req: SaveRequest = SaveRequest()):
    try:
        save_id = save_game(_get_state(), req.name)
        return {"save_id": save_id}
    except StorageError as e:
        raise HTTPException(500, detail=ErrorResponse(
            error_code=e.code, message=e.message,
        ).model_dump())


# ── 6.7 GET /api/saves ─────────────────────────────────

@router.get("/saves")
async def get_saves():
    return list_saves()


# ── 6.8 POST /api/load/{save_id} ───────────────────────

@router.post("/load/{save_id}")
async def load(save_id: int):
    global _state
    try:
        _state, migration_applied, migration_note = load_game(save_id)
        return {
            **_state.model_dump(),
            "migration_applied": migration_applied,
            "migration_note": migration_note,
        }
    except SaveNotFoundError:
        raise HTTPException(404, detail=ErrorResponse(
            error_code="save_not_found",
            message=f"存档 {save_id} 不存在",
        ).model_dump())
    except CorruptSaveError:
        raise HTTPException(500, detail=ErrorResponse(
            error_code="corrupt_save",
            message=f"存档 {save_id} 数据损坏",
        ).model_dump())


# ── 6.9 DELETE /api/save/{save_id} ─────────────────────

@router.delete("/save/{save_id}")
async def remove_save(save_id: int):
    try:
        delete_save(save_id)
        return {"ok": True}
    except SaveNotFoundError:
        raise HTTPException(404, detail=ErrorResponse(
            error_code="save_not_found",
            message=f"存档 {save_id} 不存在",
        ).model_dump())
