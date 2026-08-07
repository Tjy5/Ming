"""Shared in-memory state, locks, and infrastructure for API routes.

All route sub-modules import their shared globals from here so that
state is consistent across the application.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import set_key, unset_key
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from models.game import (
    GameState, Minister, StructuredDecree, Memorial, MemorialDraft,
    ErrorResponse, create_initial_state,
)
from models.enums import DecreeType
from engine.core import LOCK_TIMEOUT_SECONDS
from ai.provider import MockProvider, get_provider, get_rule_parse_fallback, set_rule_parse_fallback
from ai.parsers import parse_memorial_draft
from db.saves import init_db


# ── TimedLock ────────────────────────────────────────────

def _resource_busy_detail() -> dict[str, object]:
    return {
        "error": "resource_busy",
        "message": "服务器繁忙，请稍后重试",
        "retry_after": 2,
    }


class _TimedLock:
    def __init__(self, timeout_seconds: int):
        self._lock = asyncio.Lock()
        self._timeout_seconds = timeout_seconds

    def locked(self) -> bool:
        return self._lock.locked()

    async def __aenter__(self):
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self._timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise HTTPException(409, detail=_resource_busy_detail()) from exc
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._lock.locked():
            self._lock.release()


# ── In-memory state ─────────────────────────────────────

_state: GameState | None = None
_lock = _TimedLock(LOCK_TIMEOUT_SECONDS)
_provider = None

_ENV_FILE_PATH = Path(__file__).resolve().parents[1] / ".env"
_SECRET_MASK = "********"
_MAX_DIALOGUE_ROUNDS = 10
_MAX_DIALOGUE_MESSAGES = _MAX_DIALOGUE_ROUNDS * 2
_MAX_CHAT_CONVERSATION_MESSAGES = 100
_chat_conversation_buffer: list[dict[str, str]] = []

_AI_PROVIDER_SPECS: dict[str, dict[str, str | None]] = {
    "mock": {
        "api_key_env": None,
        "base_url_env": None,
        "model_env": None,
        "simple_model_env": None,
        "provider_type_env": None,
        "enable_thinking_env": None,
        "enable_thinking_simple_env": None,
        "thinking_config_env": None,
        "thinking_config_simple_env": None,
    },
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url_env": "OPENAI_BASE_URL",
        "model_env": "OPENAI_MODEL_NAME",
        "simple_model_env": "OPENAI_SIMPLE_MODEL",
        "provider_type_env": "OPENAI_PROVIDER_TYPE",
        "enable_thinking_env": "OPENAI_ENABLE_THINKING",
        "enable_thinking_simple_env": "OPENAI_ENABLE_THINKING_SIMPLE",
        "thinking_config_env": "OPENAI_THINKING_CONFIG",
        "thinking_config_simple_env": "OPENAI_THINKING_CONFIG_SIMPLE",
    },
    "google": {
        "api_key_env": "GOOGLE_API_KEY",
        "base_url_env": "GOOGLE_BASE_URL",
        "model_env": "GOOGLE_MODEL_NAME",
        "simple_model_env": "GOOGLE_SIMPLE_MODEL",
        "provider_type_env": "GOOGLE_PROVIDER_TYPE",
        "enable_thinking_env": "GOOGLE_ENABLE_THINKING",
        "enable_thinking_simple_env": "GOOGLE_ENABLE_THINKING_SIMPLE",
        "thinking_config_env": "GOOGLE_THINKING_CONFIG",
        "thinking_config_simple_env": "GOOGLE_THINKING_CONFIG_SIMPLE",
    },
    "h": {
        "api_key_env": "HOTARU_API_KEY",
        "base_url_env": "HOTARU_BASE_URL",
        "model_env": "HOTARU_MODEL",
        "simple_model_env": "HOTARU_SIMPLE_MODEL",
        "provider_type_env": "HOTARU_PROVIDER_TYPE",
        "enable_thinking_env": "HOTARU_ENABLE_THINKING",
        "enable_thinking_simple_env": "HOTARU_ENABLE_THINKING_SIMPLE",
        "thinking_config_env": "HOTARU_THINKING_CONFIG",
        "thinking_config_simple_env": "HOTARU_THINKING_CONFIG_SIMPLE",
    },
    "Z": {
        "api_key_env": "Z_API_KEY",
        "base_url_env": "Z_BASE_URL",
        "model_env": "Z_MODEL",
        "simple_model_env": "Z_SIMPLE_MODEL",
        "provider_type_env": "Z_PROVIDER_TYPE",
        "enable_thinking_env": "Z_ENABLE_THINKING",
        "enable_thinking_simple_env": "Z_ENABLE_THINKING_SIMPLE",
        "thinking_config_env": "Z_THINKING_CONFIG",
        "thinking_config_simple_env": "Z_THINKING_CONFIG_SIMPLE",
    },
}

_AI_PROVIDER_ALIASES = {
    "mock": "mock",
    "openai": "openai",
    "google": "google",
    "h": "h",
    "hotaru": "h",
    "z": "Z",
}


def _get_state() -> GameState:
    global _state
    if _state is None:
        _state = create_initial_state()
    return _state


def _set_state(s: GameState) -> None:
    global _state
    _state = s


def _get_provider():
    global _provider
    if _provider is None:
        _provider = get_provider()
    return _provider


def _trim_chat_conversation_buffer() -> None:
    if len(_chat_conversation_buffer) <= _MAX_CHAT_CONVERSATION_MESSAGES:
        return
    del _chat_conversation_buffer[:-_MAX_CHAT_CONVERSATION_MESSAGES]


def append_chat_conversation(role: str, content: str) -> None:
    normalized_role = str(role).strip().lower()
    if normalized_role not in {"user", "assistant"}:
        normalized_role = "assistant"
    normalized_content = str(content).strip()
    if not normalized_content:
        return
    _chat_conversation_buffer.append(
        {"role": normalized_role, "content": normalized_content},
    )
    _trim_chat_conversation_buffer()


def get_chat_conversation() -> list[dict[str, str]]:
    return [dict(item) for item in _chat_conversation_buffer]


def clear_chat_conversation() -> None:
    _chat_conversation_buffer.clear()





def startup():
    init_db()


# ── AI settings helpers ─────────────────────────────────

def _normalize_provider_name(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        value = os.getenv("AI_PROVIDER", "mock")
    lowered = value.lower()
    return _AI_PROVIDER_ALIASES.get(lowered, value)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _mask_secret(value: str | None) -> str:
    return _SECRET_MASK if (value or "").strip() else ""


def _resolve_submitted_secret(
    submitted: str | None,
    current: str | None,
) -> str | None:
    cleaned = _clean_optional(submitted)
    if cleaned == _SECRET_MASK:
        return _clean_optional(current)
    return cleaned


def _is_private_hostname(hostname: str | None) -> bool:
    host = (hostname or "").strip().rstrip(".").lower()
    if not host:
        return True
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_model_list_base_url(base_url: str, provider: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{provider} Base URL 仅支持 http/https")
    if not parsed.netloc:
        raise ValueError(f"{provider} Base URL 缺少主机")
    if parsed.username or parsed.password:
        raise ValueError(f"{provider} Base URL 不允许内嵌账号信息")
    if _is_private_hostname(parsed.hostname) and not _env_bool(
        "AI_MODEL_LIST_ALLOW_PRIVATE_HOSTS", False,
    ):
        raise ValueError(
            f"{provider} Base URL 指向内网地址。若确认需要，请设置 AI_MODEL_LIST_ALLOW_PRIVATE_HOSTS=1",
        )
    return base_url


def _provider_spec(provider_name: str) -> dict[str, str | None]:
    spec = _AI_PROVIDER_SPECS.get(provider_name)
    if spec is None:
        prefix = provider_name.upper().replace("-", "_").replace(" ", "_")
        return {
            "api_key_env": f"{prefix}_API_KEY",
            "base_url_env": f"{prefix}_BASE_URL",
            "model_env": f"{prefix}_MODEL",
            "simple_model_env": f"{prefix}_SIMPLE_MODEL",
            "provider_type_env": f"{prefix}_PROVIDER_TYPE",
            "enable_thinking_env": f"{prefix}_ENABLE_THINKING",
            "enable_thinking_simple_env": f"{prefix}_ENABLE_THINKING_SIMPLE",
            "thinking_config_env": f"{prefix}_THINKING_CONFIG",
            "thinking_config_simple_env": f"{prefix}_THINKING_CONFIG_SIMPLE",
        }
    return spec


def _env_value(env_name: str | None) -> str:
    if not env_name:
        return ""
    return (os.getenv(env_name) or "").strip()


def _env_json_object(env_name: str | None) -> dict[str, str | bool | int] | None:
    raw = _env_value(env_name)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logging.warning("Ignore invalid JSON in %s: %s", env_name, exc)
        return None
    if not isinstance(payload, dict):
        logging.warning("Ignore non-object JSON in %s", env_name)
        return None
    return payload


def _current_ai_settings(provider_name: str | None = None) -> dict:
    provider = _normalize_provider_name(provider_name)
    spec = _provider_spec(provider)

    api_key = _env_value(spec["api_key_env"])
    base_url = _env_value(spec["base_url_env"])
    model = _env_value(spec["model_env"])
    simple_model = _env_value(spec.get("simple_model_env"))
    provider_type = _env_value(spec.get("provider_type_env")) or ("google" if provider == "google" else "openai")

    if provider == "google":
        api_key = api_key or _env_value("OPENAI_API_KEY")
        base_url = base_url or _env_value("OPENAI_BASE_URL")
        model = model or _env_value("OPENAI_MODEL_NAME")
        simple_model = simple_model or _env_value("OPENAI_SIMPLE_MODEL")

    options = ["mock", "openai", "google", "h", "Z"]
    
    custom_providers_str = _env_value("AI_CUSTOM_PROVIDERS")
    if custom_providers_str:
        for custom_p in custom_providers_str.split(","):
            custom_p = custom_p.strip()
            if custom_p and custom_p not in options:
                options.append(custom_p)

    if provider not in options:
        options.append(provider)

    enable_thinking = _env_bool(spec.get("enable_thinking_env") or "") if spec.get("enable_thinking_env") else False
    enable_thinking_simple = _env_bool(spec.get("enable_thinking_simple_env") or "") if spec.get("enable_thinking_simple_env") else False
    thinking_config = _env_json_object(spec.get("thinking_config_env"))
    thinking_config_simple = _env_json_object(spec.get("thinking_config_simple_env"))

    return {
        "provider": provider,
        "provider_type": provider_type,
        "api_key": _mask_secret(api_key),
        "base_url": base_url,
        "model": model,
        "simple_model": simple_model,
        "enable_thinking": enable_thinking,
        "enable_thinking_simple": enable_thinking_simple,
        "thinking_config": thinking_config,
        "thinking_config_simple": thinking_config_simple,
        "provider_options": options,
    }


def _persist_env_values(updates: dict[str, str | None]) -> None:
    _ENV_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ENV_FILE_PATH.touch(exist_ok=True)

    for key, value in updates.items():
        clean = _clean_optional(value)
        if clean is None:
            unset_key(str(_ENV_FILE_PATH), key)
            os.environ.pop(key, None)
            continue
        set_key(str(_ENV_FILE_PATH), key, clean, quote_mode="never")
        os.environ[key] = clean


def _apply_ai_settings(
    *,
    provider: str,
    provider_type: str | None = None,
    api_key: str | None,
    base_url: str | None,
    model: str | None,
    simple_model: str | None = None,
    enable_thinking: bool | None = None,
    enable_thinking_simple: bool | None = None,
    thinking_config: dict[str, str | bool | int] | None = None,
    thinking_config_simple: dict[str, str | bool | int] | None = None,
) -> dict:
    global _provider

    normalized_provider = _normalize_provider_name(provider)
    spec = _provider_spec(normalized_provider)

    current_api_key = _clean_optional(_env_value(spec["api_key_env"]))
    api_key = _resolve_submitted_secret(api_key, current_api_key)
    base_url = _clean_optional(base_url)
    model = _clean_optional(model)
    simple_model = _clean_optional(simple_model)
    provider_type = _clean_optional(provider_type)
    provider_type_key = (provider_type or "").lower()

    if normalized_provider == "google" or provider_type_key in {"google", "gemini"}:
        base_url = _normalize_google_base_url(base_url)
    elif normalized_provider != "mock":
        base_url = _normalize_openai_base_url(base_url, normalized_provider)

    if normalized_provider not in {"mock", "openai", "google"}:
        if not api_key or not base_url:
            raise HTTPException(422, detail=ErrorResponse(
                error_code="invalid_ai_settings",
                message=f"{normalized_provider} 供应商必须填写 API Key 与 Base URL",
            ).model_dump())

    updates: dict[str, str | None] = {"AI_PROVIDER": normalized_provider}
    
    if normalized_provider not in ["mock", "openai", "google", "h", "Z"]:
        custom_providers_str = _env_value("AI_CUSTOM_PROVIDERS")
        existing_customs = []
        if custom_providers_str:
            existing_customs = [p.strip() for p in custom_providers_str.split(",") if p.strip()]
        
        if normalized_provider not in existing_customs:
            existing_customs.append(normalized_provider)
            updates["AI_CUSTOM_PROVIDERS"] = ",".join(existing_customs)

    if spec["api_key_env"]:
        updates[spec["api_key_env"]] = api_key
    if spec["base_url_env"]:
        updates[spec["base_url_env"]] = base_url
    if spec["model_env"]:
        updates[spec["model_env"]] = model
    if spec.get("simple_model_env"):
        updates[spec["simple_model_env"]] = simple_model

    if spec.get("provider_type_env"):
        updates[spec["provider_type_env"]] = provider_type

    if spec.get("enable_thinking_env") and enable_thinking is not None:
        updates[spec["enable_thinking_env"]] = "1" if enable_thinking else "0"
    if spec.get("enable_thinking_simple_env") and enable_thinking_simple is not None:
        updates[spec["enable_thinking_simple_env"]] = "1" if enable_thinking_simple else "0"
    if spec.get("thinking_config_env"):
        if thinking_config is not None:
            updates[spec["thinking_config_env"]] = json.dumps(
                thinking_config,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        else:
            updates[spec["thinking_config_env"]] = None
    if spec.get("thinking_config_simple_env"):
        if thinking_config_simple is not None:
            updates[spec["thinking_config_simple_env"]] = json.dumps(
                thinking_config_simple,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        else:
            updates[spec["thinking_config_simple_env"]] = None

    _persist_env_values(updates)
    _provider = None
    try:
        _provider = get_provider(normalized_provider)
    except Exception as exc:
        _provider = None
        raise HTTPException(422, detail=ErrorResponse(
            error_code="invalid_ai_settings",
            message=f"AI配置无效: {exc}",
        ).model_dump())
    return _current_ai_settings(normalized_provider)


def _delete_ai_settings(provider: str) -> dict:
    global _provider
    normalized_provider = _normalize_provider_name(provider)

    # Cannot delete mock provider (it's the fallback)
    if normalized_provider == "mock":
        raise ValueError("Mock 提供商不可删除")

    spec = _provider_spec(normalized_provider)
    
    updates: dict[str, str | None] = {}
    
    # Remove from AI_CUSTOM_PROVIDERS if present
    custom_providers_str = _env_value("AI_CUSTOM_PROVIDERS")
    if custom_providers_str:
        existing_customs = [p.strip() for p in custom_providers_str.split(",") if p.strip()]
        if normalized_provider in existing_customs:
            existing_customs.remove(normalized_provider)
            updates["AI_CUSTOM_PROVIDERS"] = ",".join(existing_customs) if existing_customs else None

    # Remove all related environment variables by setting them to None
    if spec["api_key_env"]: updates[spec["api_key_env"]] = None
    if spec["base_url_env"]: updates[spec["base_url_env"]] = None
    if spec["model_env"]: updates[spec["model_env"]] = None
    if spec.get("simple_model_env"): updates[spec["simple_model_env"]] = None
    if spec.get("provider_type_env"): updates[spec["provider_type_env"]] = None
    if spec.get("enable_thinking_env"): updates[spec["enable_thinking_env"]] = None
    if spec.get("enable_thinking_simple_env"): updates[spec["enable_thinking_simple_env"]] = None
    if spec.get("thinking_config_env"): updates[spec["thinking_config_env"]] = None
    if spec.get("thinking_config_simple_env"): updates[spec["thinking_config_simple_env"]] = None
    
    # If the active provider is the one being deleted, fallback to mock
    if _env_value("AI_PROVIDER") == normalized_provider:
        updates["AI_PROVIDER"] = "mock"
    
    _persist_env_values(updates)
    _provider = None

    return _current_ai_settings(_env_value("AI_PROVIDER") or "mock")


def _normalize_openai_base_url(base_url: str | None, provider: str) -> str:
    base = (base_url or "").strip()
    if not base and provider == "openai":
        return "https://api.openai.com/v1"
    if not base:
        return ""
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[:-len("/chat/completions")]
    return base.rstrip("/")


def _normalize_google_base_url(base_url: str | None) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return "https://generativelanguage.googleapis.com"
    for suffix in ("/v1beta", "/v1"):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    return base


async def _fetch_openai_models(
    *,
    api_key: str | None,
    base_url: str,
) -> list[str]:
    if not base_url:
        raise ValueError("缺少可用 Base URL")
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    models_url = f"{base_url.rstrip('/')}/models"
    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get(models_url, headers=headers)
        response.raise_for_status()
        payload = response.json()

    models: set[str] = set()
    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                model_id = item.get("id")
                if isinstance(model_id, str) and model_id.strip():
                    models.add(model_id.strip())
    return sorted(models)


async def _fetch_google_models(
    *,
    api_key: str,
    base_url: str,
) -> list[str]:
    models_url = f"{_normalize_google_base_url(base_url).rstrip('/')}/v1beta/models"
    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get(models_url, params={"key": api_key})
        response.raise_for_status()
        payload = response.json()

    models: set[str] = set()
    for item in (payload.get("models") or []):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            models.add(name.split("/", 1)[-1].strip())
    return sorted(models)


async def _fetch_anthropic_models(
    *,
    api_key: str,
    base_url: str | None = None,
) -> list[str]:
    """Fetch available models from Anthropic's GET /v1/models endpoint."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        base = "https://api.anthropic.com"
    models_url = f"{base}/v1/models"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get(models_url, headers=headers)
        response.raise_for_status()
        payload = response.json()

    models: set[str] = set()
    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                model_id = item.get("id")
                if isinstance(model_id, str) and model_id.strip():
                    models.add(model_id.strip())
    return sorted(models)


# ── Memorial filling ─────────────────────────────────────

async def _fill_memorial_content(
    provider, memorials: list[Memorial], state: GameState,
) -> None:
    if not memorials:
        return

    async def _fill_one(mem: Memorial):
        author = next((m for m in state.ministers if m.name == mem.author_name), None)
        if author is None:
            author = Minister(name=mem.author_name, faction=mem.author_faction)
        draft = await provider.generate_memorial(mem.trigger_reason, author, state)
        mem.content = draft.content
        mem.suggested_decrees = draft.suggested_decrees

    results = await asyncio.gather(
        *(_fill_one(m) for m in memorials), return_exceptions=True,
    )
    mock = MockProvider()
    for mem, result in zip(memorials, results):
        if isinstance(result, Exception):
            try:
                author = next((m for m in state.ministers if m.name == mem.author_name), None)
                if author is None:
                    author = Minister(name=mem.author_name, faction=mem.author_faction)
                draft = await mock.generate_memorial(mem.trigger_reason, author, state)
                mem.content = draft.content
                mem.suggested_decrees = draft.suggested_decrees
            except Exception:
                mem.content = f"臣{mem.author_name}伏惟主公圣鉴，伏乞圣裁。"


# ── Streaming helpers ────────────────────────────────────

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")
_STREAM_PROGRESS_MESSAGES = (
    "军机处正在核对政令条目……",
    "六部正在执行政令影响……",
    "翰林院正在撰写廷议叙事……",
)


def _split_stream_sentences(text: str) -> list[str]:
    normalized = (text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return []

    chunks: list[str] = []
    for paragraph in normalized.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        parts = _SENTENCE_SPLIT_RE.split(paragraph)
        for part in parts:
            item = part.strip()
            if item:
                chunks.append(item)
    return chunks or [normalized]


def _sse_event(event: str, data: dict) -> str:
    payload = json.dumps(jsonable_encoder(data), ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


NarrativeChunkCallback = Callable[[str], Awaitable[None]]


async def _generate_narrative_with_streaming(
    provider,
    attribution: dict,
    state: GameState,
    triggered: list[str],
    decree: StructuredDecree,
    stream_callback: NarrativeChunkCallback | None,
) -> str:
    if stream_callback is None:
        return await provider.generate_narrative(attribution, state, triggered, decree)

    chunks: list[str] = []
    async for chunk in provider.stream_narrative(attribution, state, triggered, decree):
        if chunk == "":
            continue
        chunks.append(chunk)
        await stream_callback(chunk)

    narrative = "".join(chunks)
    if narrative:
        return narrative
    fallback = await provider.generate_narrative(attribution, state, triggered, decree)
    if fallback and stream_callback is not None:
        await stream_callback(fallback)
    return fallback
