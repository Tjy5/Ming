"""Typed settings and transactional AI configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ai.config import AIConfigurationError
from ai.endpoint_security import UnsafeEndpointError
from ai.errors import ProviderFailure, new_request_id, public_error_detail
from ai.provider import get_rule_parse_fallback, set_rule_parse_fallback

from .ai_settings_service import get_ai_settings_service
from .debate_helpers import is_ai_provider as _is_ai_provider
from .schemas import (
    AIModelListRequest,
    AIModelListResponse,
    AISettingsApplyRequest,
    AISettingsAssessmentRequest,
    AISettingsAssessmentResponse,
    AISettingsErrorEnvelope,
    AISettingsResponse,
    AISettingsTestRequest,
    AISettingsTestResponse,
    SettingsRequest,
)
from .state import (
    _get_provider,
    _get_runtime_provider_slot,
    _lock,
    _set_runtime_provider_slot,
)


settings_router = APIRouter(prefix="/api")

AI_SETTINGS_ERROR_RESPONSES = {
    409: {"model": AISettingsErrorEnvelope, "description": "Verification or settings conflict"},
    422: {"model": AISettingsErrorEnvelope, "description": "Invalid AI settings"},
    500: {"model": AISettingsErrorEnvelope, "description": "AI settings apply failure"},
    502: {"model": AISettingsErrorEnvelope, "description": "Provider failure"},
    504: {"model": AISettingsErrorEnvelope, "description": "Provider timeout"},
}


def _raise_ai_error(exc: Exception) -> None:
    if isinstance(exc, AIConfigurationError):
        conflict_codes = {
            "ai_test_required",
            "ai_test_expired",
            "ai_test_mismatch",
            "ai_test_used",
            "ai_settings_conflict",
            "ai_configuration_required",
            "ai_configuration_invalid",
        }
        status = 409 if exc.error_code in conflict_codes else 422
        raise HTTPException(
            status,
            detail=public_error_detail(
                exc.error_code,
                request_id=new_request_id(),
                details={"field": exc.field_name} if exc.field_name else None,
            ),
        ) from None
    if isinstance(exc, UnsafeEndpointError):
        raise HTTPException(
            422,
            detail=public_error_detail(
                "invalid_base_url",
                request_id=new_request_id(),
            ),
        ) from None
    if isinstance(exc, ProviderFailure):
        if exc.error_code == "timeout":
            status = 504
        elif exc.error_code in {
            "ai_settings_apply_failed",
            "ai_settings_rollback_failed",
        }:
            status = 500
        else:
            status = 502
        raise HTTPException(status, detail=exc.public_detail()) from None
    raise exc


@settings_router.get("/capabilities")
async def get_capabilities():
    try:
        supported = _is_ai_provider(_get_provider())
    except HTTPException:
        supported = False
    return {
        "debate_supported": supported,
        "assembly_supported": supported,
        "memorial_enabled": True,
    }


@settings_router.get("/settings")
async def get_settings():
    return {"rule_parse_fallback": get_rule_parse_fallback()}


@settings_router.post("/settings")
async def update_settings(req: SettingsRequest):
    set_rule_parse_fallback(req.rule_parse_fallback)
    return {"rule_parse_fallback": get_rule_parse_fallback()}


@settings_router.get("/settings/ai", response_model=AISettingsResponse)
async def get_ai_settings(provider: str | None = None):
    return get_ai_settings_service().current_settings(provider)


@settings_router.post(
    "/settings/ai",
    response_model=AISettingsResponse,
    responses=AI_SETTINGS_ERROR_RESPONSES,
)
async def update_ai_settings(req: AISettingsApplyRequest):
    try:
        async with _lock:
            return await get_ai_settings_service().apply_draft(
                req,
                get_runtime_provider=_get_runtime_provider_slot,
                set_runtime_provider=_set_runtime_provider_slot,
            )
    except Exception as exc:
        _raise_ai_error(exc)


@settings_router.delete(
    "/settings/ai",
    response_model=AISettingsResponse,
    responses=AI_SETTINGS_ERROR_RESPONSES,
)
async def delete_ai_settings(provider: str):
    try:
        async with _lock:
            return await get_ai_settings_service().delete_settings(
                provider,
                get_runtime_provider=_get_runtime_provider_slot,
                set_runtime_provider=_set_runtime_provider_slot,
            )
    except Exception as exc:
        _raise_ai_error(exc)


@settings_router.post(
    "/settings/ai/models",
    response_model=AIModelListResponse,
    responses=AI_SETTINGS_ERROR_RESPONSES,
)
async def list_ai_models(req: AIModelListRequest):
    try:
        return await get_ai_settings_service().list_models(req)
    except Exception as exc:
        _raise_ai_error(exc)


@settings_router.post(
    "/settings/ai/test",
    response_model=AISettingsTestResponse,
    responses=AI_SETTINGS_ERROR_RESPONSES,
)
async def test_ai_connection(req: AISettingsTestRequest):
    try:
        return await get_ai_settings_service().test_draft(req)
    except Exception as exc:
        _raise_ai_error(exc)


@settings_router.post(
    "/settings/ai/assess",
    response_model=AISettingsAssessmentResponse,
    responses=AI_SETTINGS_ERROR_RESPONSES,
)
async def assess_ai_capability(req: AISettingsAssessmentRequest):
    try:
        return await get_ai_settings_service().assess_draft(req)
    except Exception as exc:
        _raise_ai_error(exc)
