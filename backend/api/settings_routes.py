"""Settings and AI configuration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from models.game import ErrorResponse
from ai.provider import get_rule_parse_fallback, set_rule_parse_fallback
from .schemas import AIModelListRequest, AISettingsRequest, SettingsRequest
from .state import (
    _apply_ai_settings,
    _clean_optional,
    _current_ai_settings,
    _env_value,
    _fetch_google_models,
    _fetch_openai_models,
    _get_provider,
    _lock,
    _normalize_google_base_url,
    _normalize_openai_base_url,
    _normalize_provider_name,
    _provider_spec,
    _resolve_submitted_secret,
    _validate_model_list_base_url,
)
from .debate_helpers import is_ai_provider as _is_ai_provider

settings_router = APIRouter(prefix="/api")


# ── GET /api/capabilities ───────────────────────────────

@settings_router.get("/capabilities")
async def get_capabilities():
    supported = _is_ai_provider(_get_provider())
    return {
        "debate_supported": supported,
        "portrait_supported": supported,
        "assembly_supported": supported,
        "memorial_enabled": True,
    }


# ── GET /api/settings ──────────────────────────────────

@settings_router.get("/settings")
async def get_settings():
    return {"rule_parse_fallback": get_rule_parse_fallback()}


@settings_router.post("/settings")
async def update_settings(req: SettingsRequest):
    set_rule_parse_fallback(req.rule_parse_fallback)
    return {"rule_parse_fallback": get_rule_parse_fallback()}


# ── AI settings ─────────────────────────────────────────

@settings_router.get("/settings/ai")
async def get_ai_settings(provider: str | None = None):
    return _current_ai_settings(provider)


@settings_router.post("/settings/ai")
async def update_ai_settings(req: AISettingsRequest):
    async with _lock:
        return _apply_ai_settings(
            provider=req.provider,
            api_key=req.api_key,
            base_url=req.base_url,
            model=req.model,
        )


@settings_router.post("/settings/ai/models")
async def list_ai_models(req: AIModelListRequest):
    current = _current_ai_settings(req.provider)
    provider = _normalize_provider_name(req.provider or current["provider"])
    spec = _provider_spec(provider)

    current_api_key = _clean_optional(_env_value(spec["api_key_env"]))
    current_base_url = _clean_optional(_env_value(spec["base_url_env"]))
    if provider == "google":
        current_api_key = current_api_key or _clean_optional(_env_value("OPENAI_API_KEY"))
        current_base_url = current_base_url or _clean_optional(_env_value("OPENAI_BASE_URL"))

    api_key = (
        _resolve_submitted_secret(req.api_key, current_api_key)
        if req.api_key is not None else current_api_key
    )
    base_url = _clean_optional(req.base_url) if req.base_url is not None else current_base_url

    if provider == "mock":
        return {"provider": provider, "models": [], "source": "mock"}

    if provider in {"openai", "h", "Z"}:
        try:
            normalized_base_url = _normalize_openai_base_url(base_url, provider)
            validated_base_url = _validate_model_list_base_url(
                normalized_base_url, provider,
            )
        except ValueError as exc:
            raise HTTPException(422, detail=ErrorResponse(
                error_code="invalid_base_url",
                message=f"模型列表地址无效: {exc}",
            ).model_dump())
        try:
            models = await _fetch_openai_models(
                api_key=api_key,
                base_url=validated_base_url,
            )
            return {"provider": provider, "models": models, "source": "openai-compatible"}
        except Exception as exc:
            raise HTTPException(502, detail=ErrorResponse(
                error_code="model_list_failed",
                message=f"获取模型列表失败: {exc}",
            ).model_dump())

    if provider == "google":
        openai_base = _normalize_openai_base_url(base_url, provider)
        if openai_base:
            try:
                validated_openai_base = _validate_model_list_base_url(
                    openai_base, "google(openai-compatible)",
                )
                models = await _fetch_openai_models(
                    api_key=api_key,
                    base_url=validated_openai_base,
                )
                if models:
                    return {
                        "provider": provider,
                        "models": models,
                        "source": "openai-compatible",
                    }
            except Exception:
                pass

        if not api_key:
            raise HTTPException(422, detail=ErrorResponse(
                error_code="missing_api_key",
                message="请先填写 Google API Key 再获取模型列表",
            ).model_dump())
        try:
            validated_google_base = _validate_model_list_base_url(
                _normalize_google_base_url(base_url), "google",
            )
        except ValueError as exc:
            raise HTTPException(422, detail=ErrorResponse(
                error_code="invalid_base_url",
                message=f"模型列表地址无效: {exc}",
            ).model_dump())
        try:
            models = await _fetch_google_models(
                api_key=api_key,
                base_url=validated_google_base,
            )
            return {"provider": provider, "models": models, "source": "google-api"}
        except Exception as exc:
            raise HTTPException(502, detail=ErrorResponse(
                error_code="model_list_failed",
                message=f"获取模型列表失败: {exc}",
            ).model_dump())

    raise HTTPException(422, detail=ErrorResponse(
        error_code="invalid_provider",
        message=f"未知AI供应商: {provider}",
    ).model_dump())
