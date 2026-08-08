"""Settings and AI configuration endpoints."""
from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, HTTPException

from models.game import ErrorResponse
from ai.provider import get_rule_parse_fallback, set_rule_parse_fallback
from ai.errors import _map_provider_error
from .schemas import AIModelListRequest, AISettingsRequest, SettingsRequest
from .state import (
    _apply_ai_settings,
    _clean_optional,
    _current_ai_settings,
    _env_value,
    _fetch_anthropic_models,
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
            provider_type=req.provider_type,
            api_key=req.api_key,
            base_url=req.base_url,
            model=req.model,
            simple_model=req.simple_model,
            enable_thinking=req.enable_thinking,
            enable_thinking_simple=req.enable_thinking_simple,
            thinking_config=req.thinking_config,
            thinking_config_simple=req.thinking_config_simple,
        )


@settings_router.delete("/settings/ai")
async def delete_ai_settings(provider: str):
    async with _lock:
        from .state import _delete_ai_settings
        try:
            return _delete_ai_settings(provider)
        except ValueError as e:
            raise HTTPException(400, detail=str(e))


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

    provider_type = (req.provider_type or current.get("provider_type") or "openai").lower()

    if provider == "google" or provider_type in ["google", "gemini"]:
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
            mapped = _map_provider_error(exc)
            raise HTTPException(502, detail=ErrorResponse(
                error_code=mapped["error_code"],
                message=f"获取模型列表失败: {mapped['message']}",
            ).model_dump())

    if provider_type == "anthropic":
        # Try dynamic model listing first, fallback to hardcoded list
        if api_key:
            try:
                models = await _fetch_anthropic_models(
                    api_key=api_key,
                    base_url=base_url,
                )
                if models:
                    return {"provider": provider, "models": models, "source": "anthropic-api"}
            except Exception:
                pass
        anthropic_models = [
            "claude-sonnet-4-6-20260217",
            "claude-opus-4-6-20260205",
            "claude-haiku-4-5-20251015",
            "claude-sonnet-4-5-20250929",
            "claude-opus-4-5-20251124",
            "claude-3-7-sonnet-latest",
            "claude-3-5-sonnet-latest",
            "claude-3-5-haiku-20241022",
        ]
        return {"provider": provider, "models": anthropic_models, "source": "anthropic-fallback"}

    # Treat all other providers as OpenAI-compatible by default
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
        mapped = _map_provider_error(exc)
        raise HTTPException(502, detail=ErrorResponse(
            error_code=mapped["error_code"],
            message=f"获取模型列表失败: {mapped['message']}",
        ).model_dump())


# ── POST /api/settings/ai/test ──────────────────────────
# 真实链路探测：用提交（或环境）的 provider/api_key/base_url/model 发起一次
# 最小 chat completion，验证端到端可用。结果按 error_code 分类（ai.errors）。

@settings_router.post("/settings/ai/test")
async def test_ai_connection(req: AISettingsRequest):
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
    model = _clean_optional(req.model) or current.get("model")

    if not api_key:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="missing_api_key",
            message="请先填写 API Key 再测试连接",
        ).model_dump())

    # 仅 OpenAI 兼容端点走真实 chat 探测；Google/Anthropic 复用模型列表探测
    provider_type = (req.provider_type or current.get("provider_type") or "openai").lower()
    try:
        if provider == "google" or provider_type in ["google", "gemini"]:
            normalized = _normalize_openai_base_url(base_url, provider)
            validated = _validate_model_list_base_url(normalized, "google(openai-compatible)")
            await _fetch_openai_models(api_key=api_key, base_url=validated)
            return {"ok": True, "error_code": None, "message": "连接成功（Google 兼容端点可达）", "latency_ms": 0}
        if provider_type == "anthropic":
            await _fetch_anthropic_models(api_key=api_key, base_url=base_url)
            return {"ok": True, "error_code": None, "message": "连接成功（Anthropic 端点可达）", "latency_ms": 0}
        # 通用 OpenAI 兼容：最小 chat completion
        normalized = _normalize_openai_base_url(base_url, provider)
        validated = _validate_model_list_base_url(normalized, provider)
        url = f"{validated.rstrip('/')}/chat/completions"
        payload = {
            "model": model or "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 4,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        latency = round((time.monotonic() - start) * 1000)
        if resp.status_code == 200:
            return {"ok": True, "error_code": None, "message": "连接成功", "latency_ms": latency}
        # 非 200：用 SDK 异常类型映射（模拟 openai 错误类）
        mapped = _map_http_status(resp.status_code)
        raise HTTPException(502, detail=ErrorResponse(
            error_code=mapped["error_code"],
            message=f"供应商返回 {resp.status_code}: {resp.text[:200]}",
        ).model_dump())
    except HTTPException:
        raise
    except Exception as exc:
        mapped = _map_provider_error(exc)
        raise HTTPException(502, detail=ErrorResponse(
            error_code=mapped["error_code"],
            message=mapped["message"],
        ).model_dump())


def _map_http_status(status: int) -> dict:
    if status == 401:
        return {"error_code": "invalid_api_key", "message": "认证失败"}
    if status == 429:
        return {"error_code": "quota", "message": "额度/限流"}
    if status == 404:
        return {"error_code": "model_not_found", "message": "模型不存在"}
    return {"error_code": "model_list_failed", "message": f"HTTP {status}"}
