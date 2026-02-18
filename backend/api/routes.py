from __future__ import annotations

import asyncio
import ipaddress
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
import re
import time
from urllib.parse import urlparse

import httpx
from dotenv import set_key, unset_key
from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from models.game import (
    GameState, Minister, StructuredDecree, DecreeResponse, HistoryEntry,
    ErrorResponse, create_initial_state, INITIAL_MINISTERS, INITIAL_FACTIONS,
    CourtAssembly, AssemblyParticipant, PolicySuggestion, clamp_state,
    FreeformResult, Memorial, MemorialDraft,
)
from models.enums import DecreeType, MinisterStatus, MemorialStatus
from engine.core import process_decree, check_preconditions, validate_target
from engine.tables import FACTION_STANCE
from engine.scripts import SCRIPT_REGISTRY
from ai.provider import PARSE_ERROR_TYPE_UNAVAILABLE, MockProvider, get_provider, get_rule_parse_fallback, set_rule_parse_fallback
from db.saves import (
    init_db, save_game, load_game, list_saves, delete_save, auto_save,
    SaveNotFoundError, CorruptSaveError, StorageError,
)

router = APIRouter(prefix="/api")

# ── In-memory state ─────────────────────────────────────

_state: GameState | None = None
_lock = asyncio.Lock()
_provider = None
_portrait_lock = asyncio.Lock()
_portrait_cooldown_until = 0.0
_PORTRAIT_COOLDOWN_SECONDS = 300
_ENV_FILE_PATH = Path(__file__).resolve().parents[1] / ".env"
_SECRET_MASK = "********"

_AI_PROVIDER_SPECS: dict[str, dict[str, str | None]] = {
    "mock": {"api_key_env": None, "base_url_env": None, "model_env": None},
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url_env": "OPENAI_BASE_URL",
        "model_env": "OPENAI_MODEL_NAME",
    },
    "google": {
        "api_key_env": "GOOGLE_API_KEY",
        "base_url_env": "GOOGLE_BASE_URL",
        "model_env": "GOOGLE_MODEL_NAME",
    },
    "h": {
        "api_key_env": "HOTARU_API_KEY",
        "base_url_env": "HOTARU_BASE_URL",
        "model_env": "HOTARU_MODEL",
    },
    "Z": {
        "api_key_env": "Z_API_KEY",
        "base_url_env": "Z_BASE_URL",
        "model_env": "Z_MODEL",
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


def _get_provider():
    global _provider
    if _provider is None:
        _provider = get_provider()
    return _provider


def _portrait_retry_after_seconds() -> int:
    remain = int(_portrait_cooldown_until - time.monotonic())
    return max(0, remain)


def startup():
    init_db()


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
        raise HTTPException(422, detail=ErrorResponse(
            error_code="invalid_provider",
            message=f"未知AI供应商: {provider_name}",
        ).model_dump())
    return spec


def _env_value(env_name: str | None) -> str:
    if not env_name:
        return ""
    return (os.getenv(env_name) or "").strip()


def _current_ai_settings(provider_name: str | None = None) -> dict:
    provider = _normalize_provider_name(provider_name)
    if provider not in _AI_PROVIDER_SPECS:
        provider = "mock"
    spec = _provider_spec(provider)

    api_key = _env_value(spec["api_key_env"])
    base_url = _env_value(spec["base_url_env"])
    model = _env_value(spec["model_env"])

    if provider == "google":
        api_key = api_key or _env_value("OPENAI_API_KEY")
        base_url = base_url or _env_value("OPENAI_BASE_URL")
        model = model or _env_value("OPENAI_MODEL_NAME")

    return {
        "provider": provider,
        "api_key": _mask_secret(api_key),
        "base_url": base_url,
        "model": model,
        "provider_options": ["mock", "openai", "google", "h", "Z"],
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
    api_key: str | None,
    base_url: str | None,
    model: str | None,
) -> dict:
    global _provider

    normalized_provider = _normalize_provider_name(provider)
    spec = _provider_spec(normalized_provider)

    current_api_key = _clean_optional(_env_value(spec["api_key_env"]))
    api_key = _resolve_submitted_secret(api_key, current_api_key)
    base_url = _clean_optional(base_url)
    model = _clean_optional(model)

    if normalized_provider in {"h", "Z"}:
        if not api_key or not base_url:
            raise HTTPException(422, detail=ErrorResponse(
                error_code="invalid_ai_settings",
                message=f"{normalized_provider} 供应商必须填写 API Key 与 Base URL",
            ).model_dump())

    updates: dict[str, str | None] = {"AI_PROVIDER": normalized_provider}
    if spec["api_key_env"]:
        updates[spec["api_key_env"]] = api_key
    if spec["base_url_env"]:
        updates[spec["base_url_env"]] = base_url
    if spec["model_env"]:
        updates[spec["model_env"]] = model

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
                mem.content = f"臣{mem.author_name}伏惟陛下圣鉴，伏乞圣裁。"


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


# ── Request / Response models ───────────────────────────

MAX_FREE_TEXT_LENGTH = 200

class DecreeRequest(BaseModel):
    decrees: list[StructuredDecree] = Field(default_factory=list)
    free_text: str | None = None
    source_script_id: str | None = None
    loyalty_effects: list[list] | None = None
    state_effects: dict[str, int] | None = None


def _apply_state_effects(state: GameState, effects: dict[str, int]) -> None:
    for key, delta in effects.items():
        parts = key.split(".")
        if parts[0] == "global" and len(parts) == 2:
            obj, field = state, parts[1]
        elif parts[0] == "region" and len(parts) == 3:
            obj = next((r for r in state.regions if r.name == parts[1]), None)
            field = parts[2]
        elif parts[0] == "faction" and len(parts) == 3:
            obj = next((f for f in state.factions if f.name == parts[1]), None)
            field = parts[2]
        else:
            continue
        if obj is not None and hasattr(obj, field):
            current = getattr(obj, field)
            if isinstance(current, (int, float)):
                setattr(obj, field, current + delta)


def _apply_loyalty_effects(state: GameState, effects: list[list]) -> None:
    for item in effects:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        name, delta = item[0], item[1]
        m = next((m for m in state.ministers if m.name == name), None)
        if m is not None and isinstance(delta, (int, float)):
            m.loyalty += int(delta)


class ParseRequest(BaseModel):
    text: str


class SaveRequest(BaseModel):
    name: str | None = None


class DebateStartRequest(BaseModel):
    category: str
    topic: str


class PortraitRequest(BaseModel):
    minister_name: str
    description: str


class MemorialResolveRequest(BaseModel):
    action: str  # approved / rejected / deferred


class ConveneAssemblyRequest(BaseModel):
    topic: str
    decree_type: str


class AdoptSuggestionRequest(BaseModel):
    suggestion_index: int


class AISettingsRequest(BaseModel):
    provider: str
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class AIModelListRequest(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    base_url: str | None = None


# ── Debate Config ─────────────────────────────────────

DEBATE_TOPICS: dict[str, list[dict[str, str]]] = {
    dt.value: [{"topic": t, "decree_type": dt.value}]
    for dt, t in {
        DecreeType.TAX_INCREASE: "是否加征赋税以充实国库",
        DecreeType.TAX_DECREASE: "是否减免赋税与民休息",
        DecreeType.RECRUIT_TROOPS: "是否征兵备战",
        DecreeType.DISBAND_TROOPS: "是否裁撤冗兵",
        DecreeType.PERSONNEL: "朝廷人事任免",
        DecreeType.DIPLOMACY: "外交邦交策略",
        DecreeType.DISASTER_RELIEF: "赈灾方略",
        DecreeType.HARSH_PUNISHMENT: "严刑峻法之议",
    }.items()
}

_FACTION_ORDER = {f.name: i for i, f in enumerate(INITIAL_FACTIONS)}


# ── Debate Helpers ────────────────────────────────────

def _is_ai_provider(provider) -> bool:
    inner = getattr(provider, "_inner", provider)
    return not isinstance(inner, MockProvider)


def _pick_active_minister(state: GameState, faction_name: str) -> Minister | None:
    by_name = {m.name: m for m in state.ministers}
    for tpl in INITIAL_MINISTERS:
        m = by_name.get(tpl.name)
        if m and m.faction == faction_name and m.status == MinisterStatus.ACTIVE:
            return m
    return None


def select_debate_ministers(state: GameState, decree_type: DecreeType) -> tuple[Minister, Minister] | None:
    stances = sorted(
        [(name, stance.get(decree_type, 0)) for name, stance in FACTION_STANCE.items()],
        key=lambda x: (-x[1], _FACTION_ORDER.get(x[0], 999)),
    )
    if len(stances) < 2:
        return None

    # Try pairing from most-supportive with most-opposing, with fallback
    for pro_name, _ in stances:
        a = _pick_active_minister(state, pro_name)
        if a is None:
            continue
        for opp_name, _ in reversed(stances):
            if opp_name == pro_name:
                continue
            b = _pick_active_minister(state, opp_name)
            if b is not None:
                return a, b
    return None


# ── 6.1 POST /api/game/new ─────────────────────────────

@router.post("/game/new")
async def new_game():
    global _state
    _state = create_initial_state()
    return _state.model_dump()


# ── 6.2 POST /api/decree ───────────────────────────────

async def _execute_decree_core(
    req: DecreeRequest,
    stream_narrative_callback: NarrativeChunkCallback | None = None,
) -> tuple[dict, list[Memorial], object, GameState]:
    global _state
    # normalize free_text
    free_text = (req.free_text or "").strip() or None
    if free_text and len(free_text) > MAX_FREE_TEXT_LENGTH:
        raise HTTPException(400, detail=ErrorResponse(
            error_code="INPUT_TOO_LONG",
            message="输入超过200字符限制",
        ).model_dump())
    if free_text and req.decrees:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="invalid_decree",
            message="decrees 与 free_text 不能同时提供",
        ).model_dump())
    if req.source_script_id:
        if req.source_script_id not in SCRIPT_REGISTRY:
            raise HTTPException(422, detail=ErrorResponse(
                error_code="INVALID_SCRIPT_ID",
                message="无效的脚本事件ID",
            ).model_dump())
    if _lock.locked():
        raise HTTPException(409, detail=ErrorResponse(
            error_code="decree_in_progress",
            message="正在处理上一道政令，请稍候",
        ).model_dump())

    _mem_triggers: list[Memorial] = []

    async with _lock:
        state = _get_state().model_copy(deep=True)
        provider = _get_provider()

        if req.source_script_id:
            if req.source_script_id in state.resolved_script_ids:
                raise HTTPException(422, detail=ErrorResponse(
                    error_code="SCRIPT_ALREADY_RESOLVED",
                    message="该脚本事件已处理",
                ).model_dump())
            active_ids = {e.script_id for e in state.active_events}
            if req.source_script_id not in active_ids:
                raise HTTPException(422, detail=ErrorResponse(
                    error_code="SCRIPT_NOT_ACTIVE",
                    message="该脚本事件当前未激活",
                ).model_dump())

        # script state_effects: apply BEFORE decrees
        if req.state_effects:
            _apply_state_effects(state, req.state_effects)

        last_response: dict | None = None

        # ── Freeform path: free_text provided, no structured decrees ──
        if free_text and not req.decrees:
            script_context = None
            if req.source_script_id:
                evt = SCRIPT_REGISTRY.get(req.source_script_id)
                if evt:
                    script_context = {
                        "title": evt.title,
                        "description": evt.rich_description,
                        "suggested_actions": [c.label for c in evt.choices],
                    }
            freeform = await provider.process_freeform(free_text, state, script_context=script_context)

            if isinstance(freeform, FreeformResult):
                if req.source_script_id and not freeform.effects and not freeform.reactions:
                    raise HTTPException(422, detail=ErrorResponse(
                        error_code="FREEFORM_EMPTY",
                        message="旨意不明，请重新输入",
                    ).model_dump())
                mem_count_before = len(state.memorials)
                delta, attribution, triggered, game_over, _reactions, _summary = process_decree(
                    state, freeform=freeform,
                )
                _mem_triggers = state.memorials[mem_count_before:]

                if _summary:
                    _summary.commentary = await provider.generate_turn_commentary(
                        _summary.model_dump(), state,
                    )

                state.history_log.append(HistoryEntry(
                    year=state.time.year, month=state.time.month,
                    decree_type="freeform",
                    decree_desc=(free_text or "")[:50],
                    delta=delta, narrative=freeform.narrative,
                ))

                if state.decree_count % 5 == 0:
                    auto_save(state)

                if stream_narrative_callback and freeform.narrative:
                    await stream_narrative_callback(freeform.narrative)

                last_response = DecreeResponse(
                    state=state, delta=delta, attribution=attribution,
                    narrative=freeform.narrative, newly_triggered_events=triggered,
                    game_time=state.time, game_over=game_over,
                    minister_reactions=_reactions,
                    turn_summary=_summary,
                    memorial_triggers=_mem_triggers,
                ).model_dump()

                if game_over:
                    pass  # fall through to commit
            else:
                # Freeform failed → fallback to parse_free_input
                parsed = await provider.parse_free_input(free_text, state)
                if isinstance(parsed, dict) and "error" in parsed:
                    is_unavailable = parsed.get("error_type") == PARSE_ERROR_TYPE_UNAVAILABLE
                    raise HTTPException(503 if is_unavailable else 422, detail=ErrorResponse(
                        error_code="parse_unavailable" if is_unavailable else "parse_error",
                        message=parsed["error"],
                    ).model_dump())
                if not isinstance(parsed, list) or not parsed:
                    raise HTTPException(422, detail=ErrorResponse(
                        error_code="parse_error",
                        message="无法识别具体政令，请使用按钮操作或描述具体政令内容",
                    ).model_dump())
                # Execute fallback structured decrees
                req = DecreeRequest(
                    decrees=parsed,
                    source_script_id=req.source_script_id,
                    loyalty_effects=req.loyalty_effects,
                    state_effects=None,  # already applied
                )

        # ── Structured path ──
        if last_response is None and req.decrees:
            decree_count = len(req.decrees)
            for decree_index, decree in enumerate(req.decrees):
                reason = check_preconditions(state, decree)
                if reason:
                    narrative = await provider.rejection_narrative(decree, reason)
                    raise HTTPException(422, detail=ErrorResponse(
                        error_code="precondition_failed",
                        message=reason,
                        details={"ai_narrative": narrative},
                    ).model_dump())

                target_err = validate_target(decree, state)
                if target_err:
                    raise HTTPException(422, detail=ErrorResponse(
                        error_code="invalid_decree",
                        message=target_err,
                    ).model_dump())

                mem_count_before = len(state.memorials)
                delta, attribution, triggered, game_over, _reactions, _summary = process_decree(state, decree)
                _mem_triggers = state.memorials[mem_count_before:]

                should_stream_narrative = (
                    stream_narrative_callback is not None
                    and (decree_index == decree_count - 1 or game_over is not None)
                )
                narrative = await _generate_narrative_with_streaming(
                    provider=provider,
                    attribution=attribution,
                    state=state,
                    triggered=triggered,
                    decree=decree,
                    stream_callback=stream_narrative_callback if should_stream_narrative else None,
                )

                if _summary:
                    _summary.commentary = await provider.generate_turn_commentary(
                        _summary.model_dump(), state,
                    )

                state.history_log.append(HistoryEntry(
                    year=state.time.year, month=state.time.month,
                    decree_type=decree.type.value,
                    decree_desc=decree.target or "",
                    delta=delta, narrative=narrative,
                ))

                if state.decree_count % 5 == 0:
                    auto_save(state)

                last_response = DecreeResponse(
                    state=state, delta=delta, attribution=attribution,
                    narrative=narrative, newly_triggered_events=triggered,
                    game_time=state.time, game_over=game_over,
                    minister_reactions=_reactions,
                    turn_summary=_summary,
                    memorial_triggers=_mem_triggers,
                ).model_dump()

                if game_over:
                    break

        if req.source_script_id:
            before_count = len(state.active_events)
            state.active_events = [
                e for e in state.active_events
                if e.script_id != req.source_script_id
            ]
            if len(state.active_events) != before_count:
                state.resolved_script_ids.add(req.source_script_id)

        if last_response is None:
            if not req.source_script_id and not free_text:
                raise HTTPException(422, detail=ErrorResponse(
                    error_code="invalid_decree",
                    message="至少需要一道政令",
                ).model_dump())
            # empty decrees (e.g. script "wait" option) — still advance turn
            mem_count_before = len(state.memorials)
            delta, attribution, triggered, game_over, _reactions, _summary = process_decree(state)
            _mem_triggers = state.memorials[mem_count_before:]
            narrative = "陛下暂且按兵不动，静观时局变化。"
            if stream_narrative_callback:
                await stream_narrative_callback(narrative)
            if _summary:
                _summary.commentary = await provider.generate_turn_commentary(
                    _summary.model_dump(), state,
                )
            state.history_log.append(HistoryEntry(
                year=state.time.year, month=state.time.month,
                decree_type="wait", decree_desc="",
                delta=delta, narrative=narrative,
            ))
            if state.decree_count % 5 == 0:
                auto_save(state)
            last_response = DecreeResponse(
                state=state, delta=delta, attribution=attribution,
                narrative=narrative, newly_triggered_events=triggered,
                game_time=state.time, game_over=game_over,
                minister_reactions=_reactions,
                turn_summary=_summary,
                memorial_triggers=_mem_triggers,
            ).model_dump()

        # script loyalty_effects: apply AFTER decrees, then clamp
        if req.loyalty_effects:
            _apply_loyalty_effects(state, req.loyalty_effects)
            clamp_state(state)

        # commit only after all checks/executions pass (atomic multi-decree semantics)
        _state = state

    # ── Fill memorial content outside lock ──
    return last_response, _mem_triggers, provider, state


async def _finalize_decree_response(
    last_response: dict, memorials: list[Memorial], provider, state: GameState,
) -> dict:
    if memorials:
        await _fill_memorial_content(provider, memorials, state)
        last_response["memorial_triggers"] = [m.model_dump() for m in memorials]
    last_response["state"] = state.model_dump()
    return last_response


@router.post("/decree")
async def execute_decree(req: DecreeRequest):
    response, memorials, provider, state = await _execute_decree_core(req)
    return await _finalize_decree_response(response, memorials, provider, state)


@router.post("/decree/stream")
async def execute_decree_stream(req: DecreeRequest):
    async def event_stream():
        core_task: asyncio.Task | None = None
        narrative_queue: asyncio.Queue[str] = asyncio.Queue()
        narrative_started = False
        heartbeat_idx = 0
        try:
            yield _sse_event(
                "progress", {"stage": "queued", "message": "军机处已接旨，正在核对政令。"},
            )

            async def _on_narrative_chunk(chunk: str) -> None:
                if chunk == "":
                    return
                await narrative_queue.put(chunk)

            core_task = asyncio.create_task(
                _execute_decree_core(
                    req,
                    stream_narrative_callback=_on_narrative_chunk,
                ),
            )

            while True:
                if core_task.done() and narrative_queue.empty():
                    break
                try:
                    chunk = await asyncio.wait_for(narrative_queue.get(), timeout=0.6)
                except asyncio.TimeoutError:
                    if core_task.done():
                        continue
                    yield _sse_event(
                        "progress",
                        {
                            "stage": "narrative" if narrative_started else "processing",
                            "message": _STREAM_PROGRESS_MESSAGES[heartbeat_idx % len(_STREAM_PROGRESS_MESSAGES)],
                        },
                    )
                    heartbeat_idx += 1
                    continue

                if not narrative_started:
                    narrative_started = True
                    yield _sse_event(
                        "progress", {"stage": "narrative", "message": "诏令已成，正在宣读……"},
                    )
                yield _sse_event("narrative", {"chunk": chunk})

            response, memorials, provider, state = await core_task

            if memorials:
                yield _sse_event(
                    "progress", {"stage": "memorial", "message": "各部奏折正在誊录上呈……"},
                )
                await _fill_memorial_content(provider, memorials, state)
                response["memorial_triggers"] = [m.model_dump() for m in memorials]

                for memorial in memorials:
                    for sentence in _split_stream_sentences(memorial.content):
                        yield _sse_event(
                            "memorial",
                            {
                                "memorial_id": memorial.id,
                                "title": memorial.title,
                                "chunk": sentence,
                            },
                        )
                        await asyncio.sleep(0.03)

            response["state"] = state.model_dump()
            yield _sse_event("final", {"response": response})
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else ErrorResponse(
                error_code="stream_http_error",
                message=str(exc.detail),
            ).model_dump()
            yield _sse_event("error", {"status": exc.status_code, "detail": detail})
        except asyncio.CancelledError:
            if core_task is not None and not core_task.done():
                core_task.cancel()
            raise
        except Exception:
            yield _sse_event("error", {
                "status": 500,
                "detail": ErrorResponse(
                    error_code="stream_error",
                    message="流式执行失败，请稍后重试",
                ).model_dump(),
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── 6.3 POST /api/decree/parse ─────────────────────────

@router.post("/decree/parse")
async def parse_decree(req: ParseRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="parse_error",
            message="请输入具体政令内容",
        ).model_dump())
    if len(text) > MAX_FREE_TEXT_LENGTH:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="parse_error",
            message=f"输入长度不能超过{MAX_FREE_TEXT_LENGTH}字",
        ).model_dump())
    provider = _get_provider()
    result = await provider.parse_free_input(text, _get_state())
    if isinstance(result, dict) and "error" in result:
        is_unavailable = result.get("error_type") == PARSE_ERROR_TYPE_UNAVAILABLE
        raise HTTPException(503 if is_unavailable else 422, detail=ErrorResponse(
            error_code="parse_unavailable" if is_unavailable else "parse_error",
            message=result["error"],
        ).model_dump())
    return [d.model_dump() for d in result]


# ── 6.4 GET /api/state ─────────────────────────────────

@router.get("/state")
async def get_state():
    state = _get_state()
    placeholder_mems = [
        m for m in state.memorials
        if m.content == "待补充奏疏内容。"
        and m.status in (MemorialStatus.PENDING, MemorialStatus.DEFERRED)
    ]
    if placeholder_mems:
        await _fill_memorial_content(_get_provider(), placeholder_mems, state)
    data = state.model_dump()
    total = len(data["history_log"])
    data["history_log"] = data["history_log"][-20:]
    data["history_total_count"] = total
    return data


# ── 6.5 GET /api/history ───────────────────────────────

@router.get("/history")
async def get_history(offset: int = 0, limit: int = 20):
    offset = max(0, offset)
    limit = max(1, min(100, limit))
    state = _get_state()
    total = len(state.history_log)
    entries = state.history_log[offset:offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "entries": [e.model_dump() for e in entries],
    }


# ── 6.6 POST /api/save ─────────────────────────────────

@router.post("/save")
async def save(req: SaveRequest = SaveRequest()):
    try:
        save_id = save_game(_get_state(), req.name)
        return {"save_id": save_id}
    except StorageError as e:
        raise HTTPException(500, detail=ErrorResponse(
            error_code=e.code, message=e.message,
        ).model_dump())


# ── 6.7 GET /api/saves ─────────────────────────────────

@router.get("/saves")
async def get_saves():
    return list_saves()


# ── 6.8 POST /api/load/{save_id} ───────────────────────

@router.post("/load/{save_id}")
async def load(save_id: int):
    global _state
    try:
        _state, migration_applied, migration_note = load_game(save_id)
        return {
            **_state.model_dump(),
            "migration_applied": migration_applied,
            "migration_note": migration_note,
        }
    except SaveNotFoundError:
        raise HTTPException(404, detail=ErrorResponse(
            error_code="save_not_found",
            message=f"存档 {save_id} 不存在",
        ).model_dump())
    except CorruptSaveError:
        raise HTTPException(500, detail=ErrorResponse(
            error_code="corrupt_save",
            message=f"存档 {save_id} 数据损坏",
        ).model_dump())


# ── 6.9 DELETE /api/save/{save_id} ─────────────────────

@router.delete("/save/{save_id}")
async def remove_save(save_id: int):
    try:
        delete_save(save_id)
        return {"ok": True}
    except SaveNotFoundError:
        raise HTTPException(404, detail=ErrorResponse(
            error_code="save_not_found",
            message=f"存档 {save_id} 不存在",
        ).model_dump())


# ── 6.10 POST /api/debate/start ────────────────────────

@router.post("/debate/start")
async def start_debate(req: DebateStartRequest):
    try:
        decree_type = DecreeType(req.category)
    except ValueError:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="invalid_debate_category",
            message="无效的朝议分类",
        ).model_dump())

    topics = DEBATE_TOPICS.get(decree_type.value, [])
    if not any(t["topic"] == req.topic for t in topics):
        raise HTTPException(422, detail=ErrorResponse(
            error_code="invalid_debate_topic",
            message="议题不属于所选分类",
        ).model_dump())

    if _lock.locked():
        raise HTTPException(409, detail=ErrorResponse(
            error_code="debate_in_progress",
            message="正在处理上一场朝议，请稍候",
        ).model_dump())

    async with _lock:
        state = _get_state()
        provider = _get_provider()

        selected = select_debate_ministers(state, decree_type)
        if selected is None:
            raise HTTPException(503, detail=ErrorResponse(
                error_code="debate_unavailable",
                message="当前无法选出可参议的大臣",
            ).model_dump())

        minister_a, minister_b = selected
        result = await provider.generate_debate_narrative(req.topic, minister_a, minister_b, state)
        if result is None:
            raise HTTPException(503, detail=ErrorResponse(
                error_code="debate_unavailable",
                message="朝议生成失败，请稍后再试",
            ).model_dump())
        return result.model_dump()


# ── 6.11 POST /api/debate/silence ──────────────────────

@router.post("/debate/silence")
async def silence_debate():
    state = _get_state()
    change = max(0, min(3, 100 - state.court_prestige))
    state.court_prestige += change
    return {"state": state.model_dump(), "prestige_change": change}


# ── 6.12 GET /api/capabilities ─────────────────────────

@router.get("/capabilities")
async def get_capabilities():
    supported = _is_ai_provider(_get_provider())
    return {
        "debate_supported": supported,
        "portrait_supported": supported,
        "assembly_supported": supported,
        "memorial_enabled": True,
    }


# ── Settings ─────────────────────────────────────────────

class SettingsRequest(BaseModel):
    rule_parse_fallback: bool


@router.get("/settings")
async def get_settings():
    return {"rule_parse_fallback": get_rule_parse_fallback()}


@router.post("/settings")
async def update_settings(req: SettingsRequest):
    set_rule_parse_fallback(req.rule_parse_fallback)
    return {"rule_parse_fallback": get_rule_parse_fallback()}


@router.get("/settings/ai")
async def get_ai_settings(provider: str | None = None):
    return _current_ai_settings(provider)


@router.post("/settings/ai")
async def update_ai_settings(req: AISettingsRequest):
    if _lock.locked():
        raise HTTPException(409, detail=ErrorResponse(
            error_code="decree_in_progress",
            message="正在处理上一道政令，请稍候再修改AI设置",
        ).model_dump())

    async with _lock:
        return _apply_ai_settings(
            provider=req.provider,
            api_key=req.api_key,
            base_url=req.base_url,
            model=req.model,
        )


@router.post("/settings/ai/models")
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


# ── 6.13 POST /api/minister/portrait ───────────────────

@router.post("/minister/portrait")
async def create_portrait(req: PortraitRequest):
    global _portrait_cooldown_until
    provider = _get_provider()
    if not _is_ai_provider(provider):
        raise HTTPException(501, detail=ErrorResponse(
            error_code="portrait_not_supported",
            message="当前AI提供方不支持立绘生成",
        ).model_dump())

    async with _portrait_lock:
        retry_after = _portrait_retry_after_seconds()
        if retry_after > 0:
            raise HTTPException(503, detail=ErrorResponse(
                error_code="portrait_generation_cooldown",
                message=f"立绘服务冷却中，请在{retry_after}秒后重试",
                details={"retry_after_seconds": retry_after},
            ).model_dump())

        portrait = await provider.generate_portrait(req.minister_name, req.description)
        if portrait is None:
            _portrait_cooldown_until = time.monotonic() + _PORTRAIT_COOLDOWN_SECONDS
            raise HTTPException(503, detail=ErrorResponse(
                error_code="portrait_generation_failed",
                message=f"立绘生成失败，已暂停自动请求{_PORTRAIT_COOLDOWN_SECONDS}秒",
                details={"retry_after_seconds": _PORTRAIT_COOLDOWN_SECONDS},
            ).model_dump())

        _portrait_cooldown_until = 0.0
        return {"portrait": portrait}


# ── 6.14 GET /api/ministers ────────────────────────────

@router.get("/ministers")
async def get_ministers():
    return [m.model_dump() for m in _get_state().ministers]


# ── 8.2 POST /api/memorial/{id}/resolve ──────────────

@router.post("/memorial/{memorial_id}/resolve")
async def resolve_memorial(memorial_id: str, req: MemorialResolveRequest):
    if req.action not in {"approved", "rejected", "deferred"}:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="invalid_action",
            message="action 必须为 approved/rejected/deferred",
        ).model_dump())

    async with _lock:
        state = _get_state()
        memorial = next((m for m in state.memorials if m.id == memorial_id), None)
        if memorial is None:
            raise HTTPException(404, detail=ErrorResponse(
                error_code="memorial_not_found",
                message=f"奏折 {memorial_id} 不存在",
            ).model_dump())

        if memorial.status != MemorialStatus.PENDING and memorial.status != MemorialStatus.DEFERRED:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="already_resolved",
                message=f"奏折已处理（当前状态：{memorial.status.value}）",
            ).model_dump())

        memorial.status = MemorialStatus(req.action)

        if req.action == "approved" and memorial.suggested_decrees:
            provider = _get_provider()
            for decree in memorial.suggested_decrees:
                reason = check_preconditions(state, decree)
                if reason:
                    continue
                target_err = validate_target(decree, state)
                if target_err:
                    continue
                delta, attr, triggered, game_over, reactions, summary = process_decree(state, decree)
                narrative = await provider.generate_narrative(attr, state, triggered, decree)
                state.history_log.append(HistoryEntry(
                    year=state.time.year, month=state.time.month,
                    decree_type=decree.type.value, decree_desc=decree.target or "",
                    delta=delta, narrative=narrative,
                ))
                if game_over:
                    break

        return {"state": state.model_dump(), "action": req.action}


# ── 8.3 POST /api/court-assembly/convene ─────────────

def _time_to_months(year: int, month: int) -> int:
    return (year - 1) * 12 + month


def select_assembly_participants(state: GameState) -> list[Minister]:
    active = [m for m in state.ministers if m.status == MinisterStatus.ACTIVE]
    seen_factions: set[str] = set()
    participants: list[Minister] = []
    sorted_ministers = sorted(active, key=lambda m: (-m.loyalty, state.ministers.index(m)))
    for m in sorted_ministers:
        if m.faction in seen_factions:
            continue
        seen_factions.add(m.faction)
        participants.append(m)
        if len(participants) >= 5:
            break
    return participants


@router.post("/court-assembly/convene")
async def convene_assembly(req: ConveneAssemblyRequest):
    try:
        decree_type = DecreeType(req.decree_type)
    except ValueError:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="invalid_decree_type",
            message="无效的政令类型",
        ).model_dump())

    async with _lock:
        state = _get_state()
        current_month = _time_to_months(state.time.year, state.time.month)

        if state.last_assembly_month >= current_month:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="assembly_cooldown",
                message="本月已召开过朝会，每月最多1次",
            ).model_dump())

        participants = select_assembly_participants(state)
        if len(participants) < 3:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="insufficient_ministers",
                message="在朝大臣不足，无法召开朝会",
            ).model_dump())

        provider = _get_provider()
        ai_result = await provider.generate_assembly_debate(req.topic, participants, state)
        ai = ai_result if isinstance(ai_result, dict) else {}

        assembly = CourtAssembly(
            topic=req.topic,
            decree_type=decree_type,
            participants=[
                AssemblyParticipant(
                    name=p.name, faction=p.faction,
                    position="", argument_text="",
                ) for p in participants
            ],
            debate_text=str(ai.get("debate_text", "")),
            consensus=str(ai.get("consensus", "")),
        )

        if isinstance(ai.get("suggestions"), list):
            from models.game import PolicySuggestion as PS
            for s in ai["suggestions"][:3]:
                if not isinstance(s, dict):
                    continue
                try:
                    dt = DecreeType(s.get("decree_type", req.decree_type))
                except (ValueError, TypeError):
                    dt = decree_type
                names = s.get("supporter_names", [])
                assembly.suggestions.append(PS(
                    title=str(s.get("title", "")),
                    description=str(s.get("description", "")),
                    related_decree=StructuredDecree(type=dt),
                    supporter_names=names if isinstance(names, list) else [],
                ))

        if isinstance(ai.get("participants"), list):
            p_map = {p.name: p for p in assembly.participants}
            for ap in ai["participants"]:
                if not isinstance(ap, dict):
                    continue
                name = ap.get("name")
                if isinstance(name, str) and name in p_map:
                    p_map[name].position = str(ap.get("position", ""))
                    p_map[name].argument_text = str(ap.get("argument_text", ""))

        state.last_assembly = assembly
        state.last_assembly_month = current_month

    return assembly.model_dump()


# ── 8.4 POST /api/court-assembly/adopt ───────────────

@router.post("/court-assembly/adopt")
async def adopt_suggestion(req: AdoptSuggestionRequest):
    mem_triggers: list[Memorial] = []
    provider = _get_provider()

    async with _lock:
        state = _get_state()
        if state.last_assembly is None:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="no_assembly",
                message="当前没有可用的朝会记录",
            ).model_dump())

        if req.suggestion_index < 0 or req.suggestion_index >= len(state.last_assembly.suggestions):
            raise HTTPException(400, detail=ErrorResponse(
                error_code="invalid_suggestion_index",
                message="建议索引越界",
            ).model_dump())

        suggestion = state.last_assembly.suggestions[req.suggestion_index]
        decree = suggestion.related_decree

        reason = check_preconditions(state, decree)
        if reason:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="precondition_failed",
                message=reason,
            ).model_dump())
        target_err = validate_target(decree, state)
        if target_err:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="invalid_target",
                message=target_err,
            ).model_dump())

        mem_count_before = len(state.memorials)
        delta, attr, triggered, game_over, reactions, summary = process_decree(state, decree)
        mem_triggers = state.memorials[mem_count_before:]
        narrative = await provider.generate_narrative(attr, state, triggered, decree)
        if summary:
            summary.commentary = await provider.generate_turn_commentary(summary.model_dump(), state)
        state.history_log.append(HistoryEntry(
            year=state.time.year, month=state.time.month,
            decree_type=decree.type.value, decree_desc=decree.target or "",
            delta=delta, narrative=narrative,
        ))
        resp = DecreeResponse(
            state=state, delta=delta, attribution=attr,
            narrative=narrative, newly_triggered_events=triggered,
            game_time=state.time, game_over=game_over,
            minister_reactions=reactions, turn_summary=summary,
            memorial_triggers=mem_triggers,
        ).model_dump()

    if mem_triggers:
        await _fill_memorial_content(provider, mem_triggers, state)
        resp["memorial_triggers"] = [m.model_dump() for m in mem_triggers]
        resp["state"] = state.model_dump()

    return resp


# ── 8.5 POST /api/court-assembly/silence ─────────────

@router.post("/court-assembly/silence")
async def silence_assembly():
    async with _lock:
        state = _get_state()
        if state.last_assembly is None:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="no_assembly",
                message="当前没有可用的朝会记录",
            ).model_dump())

        if state.last_assembly.silenced:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="already_silenced",
                message="本次朝会已喝止过，每次朝会最多1次",
            ).model_dump())

        state.last_assembly.silenced = True
        change = min(2, 100 - state.court_prestige)
        state.court_prestige += change
        return {"state": state.model_dump(), "prestige_change": change}
