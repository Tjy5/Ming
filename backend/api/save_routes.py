"""Save/load game endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from models.game import ErrorResponse
from db.saves import (
    save_game, load_game, list_saves, delete_save,
    SaveNotFoundError, CorruptSaveError, StorageError,
)
from .schemas import SaveRequest
from .state import _get_state, _set_state, _lock

save_router = APIRouter(prefix="/api")


# ── POST /api/save ──────────────────────────────────────

@save_router.post("/save")
async def save(req: SaveRequest = SaveRequest()):
    try:
        save_id = save_game(_get_state(), req.name)
        return {"save_id": save_id}
    except StorageError as e:
        raise HTTPException(500, detail=ErrorResponse(
            error_code=e.code, message=e.message,
        ).model_dump())


# ── GET /api/saves ──────────────────────────────────────

@save_router.get("/saves")
async def get_saves():
    return list_saves()


# ── POST /api/load/{save_id} ────────────────────────────

@save_router.post("/load/{save_id}")
async def load(save_id: int):
    try:
        state, migration_applied, migration_note = load_game(save_id)
        _set_state(state)
        return {
            **state.model_dump(),
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


# ── DELETE /api/save/{save_id} ──────────────────────────

@save_router.delete("/save/{save_id}")
async def remove_save(save_id: int):
    try:
        delete_save(save_id)
        return {"ok": True}
    except SaveNotFoundError:
        raise HTTPException(404, detail=ErrorResponse(
            error_code="save_not_found",
            message=f"存档 {save_id} 不存在",
        ).model_dump())
