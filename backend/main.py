from contextlib import asynccontextmanager
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ai.errors import new_request_id, public_error_detail
from api.action_service import ActionAdjudicationError
from api.routes import router
from api.save_routes import save_router
from api.settings_routes import settings_router
from api.assembly_routes import assembly_router
from api.admin_routes import admin_router
from api.chat_routes import chat_router
from api.trpg import trpg_router
from api.action_routes import action_router
from api.narrative_routes import narrative_router
from models.game import ErrorResponse
from db import worlds
from engine.settlement import SettlementValidationError
from api.state import startup as api_startup


logger = logging.getLogger(__name__)


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    safe_errors: list[dict[str, Any]] = []
    for error in exc.errors():
        location = [
            item
            for item in error.get("loc", ())
            if isinstance(item, (str, int)) and not isinstance(item, bool)
        ]
        error_type = error.get("type")
        safe_errors.append(
            {
                "type": error_type if isinstance(error_type, str) else "validation_error",
                "loc": location,
                "msg": "请求字段校验失败",
            },
        )
    return safe_errors


def _invalid_ai_settings_detail(exc: RequestValidationError) -> dict[str, Any]:
    fields = sorted(
        {
            str(location[-1])
            for error in exc.errors()
            if (location := error.get("loc"))
            and isinstance(location, (tuple, list))
            and isinstance(location[-1], (str, int))
        },
    )
    return public_error_detail(
        "invalid_ai_settings",
        request_id=new_request_id(),
        details={"fields": fields},
    )


def _invalid_action_detail(exc: RequestValidationError) -> dict[str, Any]:
    fields = sorted(
        {
            str(location[-1])
            for error in exc.errors()
            if (location := error.get("loc"))
            and isinstance(location, (tuple, list))
            and isinstance(location[-1], (str, int))
        },
    )
    return ErrorResponse(
        error_code="invalid_action_request",
        message="行动请求字段校验失败",
        details={"fields": fields},
    ).model_dump(exclude_none=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    api_startup()
    yield


app = FastAPI(title="元末纪事", lifespan=lifespan)


def _world_action_error_content(code: str, message: str, **details: object) -> dict[str, Any]:
    return {
        "detail": ErrorResponse(
            error_code=code,
            message=message,
            details=details or None,
        ).model_dump(exclude_none=True),
    }


@app.exception_handler(SettlementValidationError)
async def settlement_validation_exception_handler(
    _request: Request,
    exc: SettlementValidationError,
):
    details = {"delta_id": exc.delta_id} if exc.delta_id is not None else {}
    return JSONResponse(
        status_code=422,
        content=_world_action_error_content(exc.code, exc.message, **details),
    )


@app.exception_handler(ActionAdjudicationError)
async def action_adjudication_exception_handler(
    _request: Request,
    exc: ActionAdjudicationError,
):
    return JSONResponse(
        status_code=503,
        content=_world_action_error_content(exc.code, exc.message),
    )


@app.exception_handler(worlds.WorldStoreError)
async def world_store_exception_handler(_request: Request, exc: worlds.WorldStoreError):
    if isinstance(exc, worlds.WorldNotFoundError):
        status_code = 404
    elif isinstance(
        exc,
        (
            worlds.IdempotencyConflictError,
            worlds.StaleParentVersionError,
            worlds.ActionInProgressError,
            worlds.WorldTerminalStateError,
        ),
    ):
        status_code = 409
    else:
        status_code = 500
    return JSONResponse(
        status_code=status_code,
        content=_world_action_error_content(exc.code, exc.message),
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(
        "Request validation failed: method=%s path=%s error_count=%d",
        request.method,
        request.url.path,
        len(exc.errors()),
    )
    if request.url.path.startswith("/api/settings/ai"):
        content: dict[str, Any] = {"detail": _invalid_ai_settings_detail(exc)}
    elif request.url.path == "/api/actions":
        content = {"detail": _invalid_action_detail(exc)}
    else:
        content = {"detail": _safe_validation_errors(exc)}
    return JSONResponse(
        status_code=422,
        content=content,
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(save_router)
app.include_router(settings_router)
app.include_router(assembly_router)
app.include_router(admin_router)
app.include_router(chat_router)
app.include_router(trpg_router)
app.include_router(action_router)
app.include_router(narrative_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
