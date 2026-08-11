from __future__ import annotations

from fastapi import APIRouter, HTTPException

from db import worlds
from engine.activity import ActivityContractError, find_activity
from engine.settlement import SettlementValidationError
from models.game import ErrorResponse
from models.settlement import ActionIntent
from models.world import Activity, ActivityId, BranchId, GameId

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
)
from .state import _get_provider, _publish_world_head, _reload_world_head


action_router = APIRouter(prefix="/api")
_action_service_override: ActionService | None = None
_default_action_service: ActionService | None = None


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
    except (worlds.IdempotencyConflictError, worlds.StaleParentVersionError) as exc:
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
    return ActionExecutionResponse(state=state, result=execution.result)


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
    return ActivityBatchExecutionResponse(
        state=execution.state,
        activity=execution.activity,
        results=list(execution.results),
        processing=execution.processing,
        continuation_cursor=execution.continuation_cursor,
    )
