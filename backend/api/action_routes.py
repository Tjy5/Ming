from __future__ import annotations

from fastapi import APIRouter, HTTPException

from db import worlds
from engine.activity import ActivityContractError, find_activity
from engine.lifecycle import DefaultLifecyclePlanner
from engine.settlement import SettlementValidationError
from engine.world_state import world_state_projection
from models.game import ErrorResponse
from models.settlement import ActionIntent, SettlementFacts
from models.world import Activity, ActivityId, BranchId, GameId, VersionId
from models.world_state import WorldStateProjection

from .action_service import (
    AIActionAdjudicator,
    ActionAdjudicationError,
    ActionService,
)
from .schemas import (
    ActionErrorEnvelope,
    ActionExecutionResponse,
    ActivityBatchExecutionResponse,
    ActivityContinueRequest,
    WorldBookmarkRequest,
    WorldBookmarkResponse,
    WorldBookmarkListResponse,
    WorldRetentionResponse,
    WorldRetentionCollectRequest,
    WorldRetentionCollectResponse,
    WorldLifecycleResponse,
    WorldBranchListResponse,
    WorldVersionListResponse,
)
from .state import _get_provider, _publish_world_head, _reload_world_head
from .narrative_routes import generate_committed_narrative


action_router = APIRouter(prefix="/api")
_action_service_override: ActionService | None = None
_default_action_service: ActionService | None = None


@action_router.get("/worlds/{game_id}/branches", response_model=WorldBranchListResponse)
def list_world_branches(game_id: GameId) -> WorldBranchListResponse:
    try:
        return WorldBranchListResponse(branches=worlds.list_branches(game_id))
    except worlds.WorldNotFoundError as exc:
        raise HTTPException(404, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None


@action_router.get("/worlds/{game_id}/branches/{branch_id}/versions", response_model=WorldVersionListResponse)
def list_world_versions(game_id: GameId, branch_id: BranchId) -> WorldVersionListResponse:
    try:
        return WorldVersionListResponse(versions=worlds.list_versions(game_id, branch_id))
    except worlds.WorldNotFoundError as exc:
        raise HTTPException(404, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None


@action_router.post("/worlds/{game_id}/versions/{version_id}/branch", response_model=WorldLifecycleResponse)
def branch_world_version(game_id: GameId, version_id: VersionId) -> WorldLifecycleResponse:
    try:
        source = worlds.load_version(version_id)
        if source.ref.game_id != game_id:
            raise worlds.WorldNotFoundError("version", str(version_id))
        branch = worlds.create_branch_from_version(version_id)
        snapshot = worlds.load_version(branch.version_id)
        # Keep the process-local compatibility cache aligned with the newly
        # selected branch.  Without publishing here, the response shows the
        # forked state while subsequent legacy-compatible routes still read the
        # previous branch head.
        _publish_world_head(snapshot.state, snapshot.ref)
        return WorldLifecycleResponse(
            state=snapshot.state,
            branch=worlds.get_branch(game_id, branch.branch_id),
            version=branch,
        )
    except worlds.WorldNotFoundError as exc:
        raise HTTPException(404, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldTerminalStateError as exc:
        raise HTTPException(409, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None


@action_router.post("/worlds/{game_id}/bookmarks", response_model=WorldBookmarkResponse)
def create_world_bookmark(game_id: GameId, request: WorldBookmarkRequest) -> WorldBookmarkResponse:
    if request.game_id != game_id:
        raise HTTPException(404, detail=_error_detail("world_not_found", "指定版本不属于请求的游戏"))
    try:
        bookmark = worlds.create_bookmark(game_id, request.branch_id, request.version_id, request.name)
        return WorldBookmarkResponse(bookmark=bookmark)
    except worlds.WorldNotFoundError as exc:
        raise HTTPException(404, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None


@action_router.get(
    "/worlds/{game_id}/bookmarks",
    response_model=WorldBookmarkListResponse,
)
def list_world_bookmarks(game_id: GameId, branch_id: BranchId | None = None) -> WorldBookmarkListResponse:
    try:
        return WorldBookmarkListResponse(
            bookmarks=worlds.list_bookmarks(game_id, branch_id),
        )
    except worlds.WorldNotFoundError as exc:
        raise HTTPException(404, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None


@action_router.get(
    "/worlds/{game_id}/retention",
    response_model=WorldRetentionResponse,
)
def world_retention_report(
    game_id: GameId,
    branch_id: BranchId | None = None,
    recent_limit: int = 100,
) -> WorldRetentionResponse:
    """Return a dry-run retention report; no versions are deleted by this API."""
    try:
        plan = worlds.plan_retention(game_id, branch_id, recent_limit=recent_limit)
        return WorldRetentionResponse(
            game_id=plan.game_id,
            branch_id=plan.branch_id,
            recent_limit=plan.recent_limit,
            protected_version_ids=list(plan.protected_version_ids),
            monthly_recovery_version_ids=list(plan.monthly_recovery_version_ids),
            delete_version_ids=list(plan.delete_version_ids),
            reasons={key: list(value) for key, value in plan.reasons.items()},
        )
    except ValueError as exc:
        raise HTTPException(422, detail=_error_detail("invalid_retention_request", str(exc))) from None
    except worlds.WorldNotFoundError as exc:
        raise HTTPException(404, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None


@action_router.post(
    "/worlds/{game_id}/retention/collect",
    response_model=WorldRetentionCollectResponse,
    responses={404: {"model": ActionErrorEnvelope}, 422: {"model": ActionErrorEnvelope}, 500: {"model": ActionErrorEnvelope}},
)
def collect_world_retention(
    game_id: GameId,
    request: WorldRetentionCollectRequest,
) -> WorldRetentionCollectResponse:
    """Run retention GC after an explicit, typed enable acknowledgement."""
    try:
        result = worlds.collect_retention(
            game_id,
            request.branch_id,
            recent_limit=request.recent_limit,
            enabled=request.enabled,
        )
        plan = result.plan
        return WorldRetentionCollectResponse(
            audit_id=result.audit_id,
            game_id=plan.game_id,
            branch_id=plan.branch_id,
            recent_limit=plan.recent_limit,
            mode=plan.mode,
            enabled=result.enabled,
            committed=result.committed,
            deleted_version_ids=list(result.deleted_version_ids),
            deleted_settlement_ids=list(result.deleted_settlement_ids),
            blocked_version_ids=list(result.blocked_version_ids),
            protected_version_ids=list(plan.protected_version_ids),
            monthly_recovery_version_ids=list(plan.monthly_recovery_version_ids),
            reasons={key: list(value) for key, value in plan.reasons.items()},
        )
    except ValueError as exc:
        raise HTTPException(422, detail=_error_detail("invalid_retention_request", str(exc))) from None
    except worlds.WorldNotFoundError as exc:
        raise HTTPException(404, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None


@action_router.delete("/worlds/{game_id}/bookmarks/{bookmark_id}")
def delete_world_bookmark(game_id: GameId, bookmark_id: str) -> None:
    try:
        worlds.delete_bookmark(bookmark_id, game_id=game_id)
    except worlds.WorldNotFoundError as exc:
        raise HTTPException(404, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None


@action_router.get("/settlements/{settlement_id}", response_model=SettlementFacts)
def get_settlement(settlement_id: str):
    try:
        return worlds.get_settlement(settlement_id)
    except worlds.WorldNotFoundError as exc:
        raise HTTPException(404, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None


def set_action_service_for_testing(service: ActionService | None) -> None:
    global _action_service_override
    _action_service_override = service


def _get_action_service() -> ActionService:
    global _default_action_service
    if _action_service_override is not None:
        return _action_service_override
    if _default_action_service is None:
        _default_action_service = ActionService(
            adjudicator=AIActionAdjudicator(_get_provider),
            lifecycle_planner=DefaultLifecyclePlanner(),
        )
    return _default_action_service


def _error_detail(code: str, message: str, *, delta_id: str | None = None) -> dict:
    details = {"delta_id": delta_id} if delta_id is not None else None
    return ErrorResponse(
        error_code=code,
        message=message,
        details=details,
    ).model_dump(exclude_none=True)


@action_router.post(
    "/actions",
    response_model=ActionExecutionResponse,
    responses={
        404: {"model": ActionErrorEnvelope},
        409: {"model": ActionErrorEnvelope},
        422: {"model": ActionErrorEnvelope},
        500: {"model": ActionErrorEnvelope},
        503: {"model": ActionErrorEnvelope},
    },
)
async def execute_action(intent: ActionIntent) -> ActionExecutionResponse:
    try:
        execution = await _get_action_service().execute(intent)
    except SettlementValidationError as exc:
        raise HTTPException(
            422,
            detail=_error_detail(exc.code, exc.message, delta_id=exc.delta_id),
        ) from None
    except ActionAdjudicationError as exc:
        raise HTTPException(503, detail=_error_detail(exc.code, exc.message)) from None
    except (
        worlds.IdempotencyConflictError,
        worlds.StaleParentVersionError,
        worlds.WorldTerminalStateError,
    ) as exc:
        raise HTTPException(409, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.ActionInProgressError as exc:
        raise HTTPException(409, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldNotFoundError as exc:
        raise HTTPException(404, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None

    try:
        _publish_world_head(execution.state, execution.result.version)
        state = execution.state
    except Exception:
        # The settlement is already durable. Recover the discardable cache from
        # the committed branch head instead of surfacing a false commit failure.
        state = _reload_world_head(intent.game_id, intent.branch_id)
    narrative = await generate_committed_narrative(
        state=state,
        facts=execution.result.facts,
        path_id="unified_action",
        topic_id=intent.action_kind,
        action_text=intent.raw_text,
        reuse_current=execution.result.replayed,
    )
    return ActionExecutionResponse(
        state=state,
        result=execution.result,
        narrative=narrative,
    )


@action_router.get(
    "/activities/{game_id}/{branch_id}/{activity_id}",
    response_model=Activity,
    responses={404: {"model": ActionErrorEnvelope}, 500: {"model": ActionErrorEnvelope}},
)
def get_activity(
    game_id: GameId,
    branch_id: BranchId,
    activity_id: ActivityId,
) -> Activity:
    try:
        snapshot = worlds.load_branch_head(game_id, branch_id)
        _, activity = find_activity(snapshot.state, activity_id)
        return activity
    except (worlds.WorldNotFoundError, ActivityContractError) as exc:
        code = getattr(exc, "code", "activity_not_found")
        message = getattr(exc, "message", "活动不存在")
        raise HTTPException(404, detail=_error_detail(code, message)) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None


@action_router.get(
    "/world-state/{game_id}/{branch_id}/{version_id}",
    response_model=WorldStateProjection,
    responses={404: {"model": ActionErrorEnvelope}, 500: {"model": ActionErrorEnvelope}},
)
def get_world_state_projection(
    game_id: GameId,
    branch_id: BranchId,
    version_id: VersionId,
) -> WorldStateProjection:
    """Return one immutable version-addressed projection for UI/narrative consumers."""

    try:
        snapshot = worlds.load_version(version_id)
    except worlds.WorldNotFoundError as exc:
        raise HTTPException(404, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None
    if snapshot.ref.game_id != game_id or snapshot.ref.branch_id != branch_id:
        raise HTTPException(
            404,
            detail=_error_detail(
                "world_not_found",
                "指定版本不属于请求的游戏世界线",
            ),
        )
    try:
        recent_sources = [
            attribution
            for facts in worlds.list_settlements(game_id, branch_id)
            if facts.result_version_id == version_id
            for attribution in facts.world_state_attribution
        ]
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None
    return world_state_projection(snapshot.state, recent_sources=recent_sources)


@action_router.post(
    "/activities/{activity_id}/continue",
    response_model=ActivityBatchExecutionResponse,
    responses={
        404: {"model": ActionErrorEnvelope},
        409: {"model": ActionErrorEnvelope},
        422: {"model": ActionErrorEnvelope},
        500: {"model": ActionErrorEnvelope},
        503: {"model": ActionErrorEnvelope},
    },
)
async def continue_activity(
    activity_id: ActivityId,
    request: ActivityContinueRequest,
) -> ActivityBatchExecutionResponse:
    try:
        execution = await _get_action_service().continue_activity_batch(
            game_id=request.game_id,
            branch_id=request.branch_id,
            expected_parent_version_id=request.expected_parent_version_id,
            activity_id=activity_id,
            max_checkpoints=request.max_checkpoints,
        )
    except SettlementValidationError as exc:
        raise HTTPException(
            422,
            detail=_error_detail(exc.code, exc.message, delta_id=exc.delta_id),
        ) from None
    except ActionAdjudicationError as exc:
        raise HTTPException(503, detail=_error_detail(exc.code, exc.message)) from None
    except (worlds.IdempotencyConflictError, worlds.StaleParentVersionError) as exc:
        raise HTTPException(409, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldNotFoundError as exc:
        raise HTTPException(404, detail=_error_detail(exc.code, exc.message)) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(500, detail=_error_detail(exc.code, exc.message)) from None

    if execution.results:
        try:
            _publish_world_head(execution.state, execution.results[-1].version)
        except Exception:
            try:
                reloaded_state = _reload_world_head(request.game_id, request.branch_id)
                _, reloaded_activity = find_activity(reloaded_state, activity_id)
            except worlds.WorldStoreError as exc:
                raise HTTPException(
                    500,
                    detail=_error_detail(exc.code, exc.message),
                ) from None
            except ActivityContractError as exc:
                raise HTTPException(
                    500,
                    detail=_error_detail(
                        "activity_recovery_failed",
                        exc.message,
                    ),
                ) from None
            execution = execution.__class__(
                state=reloaded_state,
                activity=reloaded_activity,
                results=execution.results,
                processing=execution.processing,
                continuation_cursor=execution.continuation_cursor,
            )
    narrative = None
    if execution.results:
        # Activity checkpoints are already committed by ``continue_activity_batch``.
        # Narrative generation is strictly post-commit and receives only the last
        # settlement facts, so retries/regeneration never execute the activity again.
        last_result = execution.results[-1]
        narrative = await generate_committed_narrative(
            state=execution.state,
            facts=last_result.facts,
            path_id="unified_action",
            topic_id="activity_checkpoint",
            action_text=f"继续活动：{execution.activity.intent}",
            reuse_current=False,
        )
    return ActivityBatchExecutionResponse(
        state=execution.state,
        activity=execution.activity,
        results=list(execution.results),
        processing=execution.processing,
        continuation_cursor=execution.continuation_cursor,
        narrative=narrative,
    )
