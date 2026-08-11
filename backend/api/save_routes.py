"""Save/load game endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from models.game import ErrorResponse
from db import worlds
from db.saves import (
    save_game, load_game, list_saves, delete_save,
    SaveNotFoundError, CorruptSaveError, IncompatibleSaveError, StorageError,
)
from .schemas import SaveRequest
from .state import _get_state, _publish_world_head, _lock

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
        root = worlds.create_game_with_root(
            state,
            protected=True,
            source_kind="legacy_save",
            source_ref=str(save_id),
        )
        snapshot = worlds.load_version(root.version_id)
        _publish_world_head(snapshot.state, snapshot.ref)
        state = snapshot.state
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
    except IncompatibleSaveError:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="incompatible_save",
            message=f"存档 {save_id} 来自旧剧本（如崇祯朝），与当前元末明初剧本不兼容",
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
