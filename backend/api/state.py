"""Shared in-memory state, locks, and infrastructure for API routes.

All route sub-modules import their shared globals from here so that
state is consistent across the application.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from models.game import (
    GameState, Minister, StructuredDecree, Memorial, create_initial_state,
)
from engine.core import LOCK_TIMEOUT_SECONDS
from ai.fallbacks import template_memorial
from ai.config import AIConfigurationError
from ai.errors import new_request_id, public_error_detail
from ai.provider import get_provider
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

_MAX_DIALOGUE_ROUNDS = 10
_MAX_DIALOGUE_MESSAGES = _MAX_DIALOGUE_ROUNDS * 2
_MAX_CHAT_CONVERSATION_MESSAGES = 100
_chat_conversation_buffer: list[dict[str, str]] = []

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
        try:
            _provider = get_provider()
        except AIConfigurationError as exc:
            raise HTTPException(
                409,
                detail=public_error_detail(
                    exc.error_code,
                    request_id=new_request_id(),
                ),
            ) from None
    return _provider


def _get_runtime_provider_slot():
    return _provider


def _set_runtime_provider_slot(provider) -> None:
    global _provider
    _provider = provider


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
        # 状态一致性（惰性导入防 engine 初始化环）：奏疏内容过校验/净化
        from engine.state_consistency import sanitize_ai_text
        mem.content = sanitize_ai_text(draft.content, state)
        mem.suggested_decrees = draft.suggested_decrees

    results = await asyncio.gather(
        *(_fill_one(m) for m in memorials), return_exceptions=True,
    )
    for mem, result in zip(memorials, results):
        if isinstance(result, Exception):
            try:
                author = next((m for m in state.ministers if m.name == mem.author_name), None)
                if author is None:
                    author = Minister(name=mem.author_name, faction=mem.author_faction)
                draft = template_memorial(mem.trigger_reason, author, state)
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
    # 状态一致性闭环（engine.state_consistency，惰性导入防 engine 初始化环）：
    # 非流式可完整走 校验→重试→净化；流式无法事后重试（文本已推送），
    # 入库/响应副本一律过校验净化，流式残留由 prompt 守卫（build_prompt_guard）兜底。
    from engine.state_consistency import ensure_narrative_consistent, sanitize_ai_text

    if stream_callback is None:
        return await ensure_narrative_consistent(
            provider, state,
            generate=lambda fix_instruction=None: provider.generate_narrative(
                attribution, state, triggered, decree, fix_instruction=fix_instruction,
            ),
        )

    chunks: list[str] = []
    async for chunk in provider.stream_narrative(attribution, state, triggered, decree):
        if chunk == "":
            continue
        chunks.append(chunk)
        await stream_callback(chunk)

    narrative = "".join(chunks)
    if narrative:
        return sanitize_ai_text(narrative, state)
    fallback = await provider.generate_narrative(attribution, state, triggered, decree)
    if fallback and stream_callback is not None:
        await stream_callback(fallback)
    return sanitize_ai_text(fallback or "", state)
