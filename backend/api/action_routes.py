from __future__ import annotations

from fastapi import APIRouter, HTTPException

from db import worlds
from engine.settlement import SettlementValidationError
from models.game import ErrorResponse
from models.settlement import ActionIntent

from .action_service import (
    AIActionAdjudicator,
    ActionAdjudicationError,
    ActionService,
)
from .schemas import ActionErrorEnvelope, ActionExecutionResponse
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
