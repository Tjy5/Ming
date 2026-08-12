"""Save/load game endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from models.game import ErrorResponse
from models.world import BranchId, GameId
from db import worlds
from db.saves import (
    save_game, list_saves, delete_save,
    SaveNotFoundError, StorageError,
)
from .schemas import (
    SaveRequest,
    WorldForkRequest,
    WorldLifecycleResponse,
    WorldSwitchRequest,
    WorldVersionListResponse,
)
from .state import _get_state, _publish_world_head, _lock
from . import state as api_state

save_router = APIRouter(prefix="/api")


# ── POST /api/save ──────────────────────────────────────

@save_router.post("/save")
async def save(req: SaveRequest = SaveRequest()):
    try:
        # Once a world graph exists, manual saves are immutable bookmarks that
        # point at the current version.  Legacy rows remain the fallback for
        # clients bootstrapping a world before its first durable head exists.
        ref = api_state._get_world_head_ref()
        if ref is not None:
            bookmark = worlds.create_bookmark(
                ref.game_id,
                ref.branch_id,
                ref.version_id,
                req.name or "手动书签",
            )
            return {"save_id": None, "bookmark": bookmark}
        save_id = save_game(_get_state(), req.name)
        return {"save_id": save_id}
    except StorageError as e:
        raise HTTPException(500, detail=ErrorResponse(
            error_code=e.code, message=e.message,
        ).model_dump())


# ── GET /api/saves ──────────────────────────────────────

@save_router.get("/saves")
async def get_saves():
    rows = list_saves()
    ref = api_state._get_world_head_ref()
    if ref is not None:
        rows = [
            *rows,
            *[
                {
                    "save_id": None,
                    "name": bookmark.name,
                    "created_at": bookmark.created_at.isoformat(),
                    "game_id": str(bookmark.game_id),
                    "branch_id": str(bookmark.branch_id),
                    "version_id": str(bookmark.version_id),
                    "bookmark_id": str(bookmark.bookmark_id),
                }
                for bookmark in worlds.list_bookmarks(ref.game_id)
            ],
        ]
    return rows


# ── Immutable world branches ─────────────────────────────

@save_router.get(
    "/worlds/{game_id}/{branch_id}/versions",
    response_model=WorldVersionListResponse,
)
async def get_world_versions(game_id: GameId, branch_id: BranchId):
    worlds.get_branch(game_id, branch_id)
    return WorldVersionListResponse(
        versions=worlds.list_versions(game_id, branch_id),
    )


@save_router.post("/worlds/fork", response_model=WorldLifecycleResponse)
async def fork_world(req: WorldForkRequest):
    async with _lock:
        source = worlds.load_version(req.version_id)
        if (
            source.ref.game_id != req.game_id
            or source.ref.branch_id != req.branch_id
        ):
            raise worlds.WorldNotFoundError("version", str(req.version_id))
        fork_ref = worlds.create_branch_from_version(req.version_id)
        snapshot = worlds.load_version(fork_ref.version_id)
        branch = worlds.get_branch(fork_ref.game_id, fork_ref.branch_id)
        _publish_world_head(snapshot.state, snapshot.ref)
        return WorldLifecycleResponse(
            state=snapshot.state,
            branch=branch,
            version=snapshot.ref,
        )


@save_router.post("/worlds/switch", response_model=WorldLifecycleResponse)
async def switch_world(req: WorldSwitchRequest):
    async with _lock:
        snapshot = worlds.load_branch_head(req.game_id, req.branch_id)
        branch = worlds.get_branch(req.game_id, req.branch_id)
        _publish_world_head(snapshot.state, snapshot.ref)
        return WorldLifecycleResponse(
            state=snapshot.state,
            branch=branch,
            version=snapshot.ref,
        )


# ── POST /api/load/{save_id} ────────────────────────────

@save_router.post("/load/{save_id}")
async def load(save_id: int):
    try:
        imported = worlds.import_legacy_save(save_id)
        snapshot = worlds.load_version(imported.version.version_id)
        _publish_world_head(snapshot.state, snapshot.ref)
        state = snapshot.state
        return {
            **state.model_dump(),
            "migration_applied": imported.migration_applied,
            "migration_note": (
                f"旧存档已自动迁移：{'；'.join(imported.migration_notes)}"
                if imported.migration_notes
                else ""
            ),
        }
    except worlds.LegacySaveNotFoundError:
        raise HTTPException(404, detail=ErrorResponse(
            error_code="save_not_found",
            message=f"存档 {save_id} 不存在",
        ).model_dump())
    except worlds.LegacySaveIncompatibleError:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="incompatible_save",
            message=f"存档 {save_id} 来自旧剧本（如崇祯朝），与当前元末明初剧本不兼容",
        ).model_dump())
    except worlds.LegacySaveCorruptError:
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
