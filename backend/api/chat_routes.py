"""Chat-mode API routes."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from engine.core import finalize_month_advance, prepare_month_advance
from models.game import ErrorResponse, GameEvent, GameState

from .routes import _decide_script_triggers_for_state, execute_decree
from .schemas import ChatRequest, DecreeRequest
from .state import (
    _get_provider,
    _get_state,
    _lock,
    _set_state,
    _split_stream_sentences,
    _sse_event,
    append_chat_conversation,
    get_chat_conversation,
)

chat_router = APIRouter(prefix="/api")

_INTENT_CONFIDENCE_THRESHOLD = 0.7
EXPLORE_PREFIX = "详细介绍当前局势："
_DELTA_FIELDS = (
    "national_treasury",
    "imperial_treasury",
    "population",
    "military_strength",
    "civil_morale",
    "military_morale",
    "court_prestige",
)
_EFFECT_LABELS = {
    "national_treasury": "国库",
    "imperial_treasury": "内帑",
    "population": "人口",
    "military_strength": "兵力",
    "civil_morale": "民心",
    "military_morale": "军心",
    "court_prestige": "威望",
}


def _normalize_chat_intent(classified: dict) -> tuple[str, float, str]:
    if not isinstance(classified, dict):
        return "execute", 0.0, "分类结果无效，默认执行分支"

    if "error" in classified:
        return "execute", 0.0, "分类服务不可用，默认执行分支"

    intent = str(classified.get("intent", "")).strip().lower()
    if intent not in {"query", "execute", "advance_month"}:
        intent = "execute"

    raw_confidence = classified.get("confidence", 0.0)
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    reason = str(classified.get("reason", "")).strip() or "AI未给出分类理由"
    return intent, confidence, reason


def _is_explore_message(message: str) -> bool:
    return message.startswith(EXPLORE_PREFIX)


def _find_blocking_event(state: GameState) -> GameEvent | None:
    return next(
        (event for event in state.active_events if event.is_scripted and event.is_blocking),
        None,
    )


def _blocking_event_error_detail(event: GameEvent) -> dict:
    return ErrorResponse(
        error_code="blocking_event_pending",
        message="当前有待处理的阻断剧情事件，请先处理后再执行该操作",
        details={"event": event.model_dump()},
    ).model_dump()


def _has_effects(delta: dict[str, int | float]) -> bool:
    return any(value != 0 for value in delta.values())


def _format_effect_summary(delta: dict[str, int | float]) -> str:
    parts: list[str] = []
    for key, value in delta.items():
        if value == 0:
            continue
        label = _EFFECT_LABELS.get(key, key)
        sign = "+" if value > 0 else ""
        if isinstance(value, float) and not float(value).is_integer():
            rendered = f"{value:.2f}".rstrip("0").rstrip(".")
        else:
            rendered = f"{int(value)}"
        parts.append(f"{label} {sign}{rendered}")
    return " | ".join(parts)


def _state_delta(before: GameState, after: GameState) -> dict[str, int]:
    delta: dict[str, int] = {}
    for field in _DELTA_FIELDS:
        before_value = int(getattr(before, field))
        after_value = int(getattr(after, field))
        diff = after_value - before_value
        if diff != 0:
            delta[field] = diff
    return delta


def _stream_chunks(text: str) -> list[str]:
    chunks = _split_stream_sentences(text)
    if chunks:
        return chunks
    return [text] if text else []


def _normalize_minister_reactions(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []

    reactions: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        minister_name = str(item.get("minister_name", "")).strip()
        faction = str(item.get("faction", "")).strip()
        reaction_type = str(item.get("reaction_type", "")).strip()
        reaction_text = str(item.get("reaction_text", "")).strip()
        loyalty_change_raw = item.get("loyalty_change", 0)
        loyalty_change = (
            int(loyalty_change_raw)
            if isinstance(loyalty_change_raw, (int, float))
            else 0
        )
        reactions.append(
            {
                "minister_name": minister_name,
                "faction": faction,
                "reaction_type": reaction_type,
                "reaction_text": reaction_text,
                "loyalty_change": loyalty_change,
            },
        )
    return reactions


@chat_router.post("/chat")
async def chat_stream(req: ChatRequest):
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="chat_empty_message",
            message="请输入对话内容",
        ).model_dump())

    async def event_stream():
        try:
            async with _lock:
                provider = _get_provider()
                state_snapshot = _get_state().model_copy(deep=True)
                append_chat_conversation("user", message)
                history_for_model = get_chat_conversation()

            is_explore_message = _is_explore_message(message)
            if is_explore_message:
                intent, confidence, reason = (
                    "query",
                    1.0,
                    f"命中探索前缀“{EXPLORE_PREFIX}”，强制查询分支",
                )
            else:
                classified = await provider.classify_chat_intent(
                    message,
                    state_snapshot,
                    history_for_model,
                )
                intent, confidence, reason = _normalize_chat_intent(classified)

            if confidence < _INTENT_CONFIDENCE_THRESHOLD and intent != "execute":
                if is_explore_message:
                    intent = "query"
                    reason = (
                        f"{reason}（置信度{confidence:.2f}低于{_INTENT_CONFIDENCE_THRESHOLD:.2f}，"
                        "但命中探索前缀，回退查询分支）"
                    )
                else:
                    intent = "execute"
                    reason = (
                        f"{reason}（置信度{confidence:.2f}低于{_INTENT_CONFIDENCE_THRESHOLD:.2f}，回退执行分支）"
                    )

            yield _sse_event("intent", {
                "intent": intent,
                "confidence": confidence,
                "reason": reason,
            })

            reply = ""
            delta: dict[str, int | float] = {}
            effects_applied = False
            state_payload: dict | None = None
            minister_reactions: list[dict[str, object]] = []
            triggered_events: list[str] = []
            new_ministers: list[str] = []
            game_over: dict | None = None

            if intent == "query":
                reply = await provider.chat_query(message, state_snapshot, history_for_model)
                for chunk in _stream_chunks(reply):
                    yield _sse_event("narrative_chunk", {"chunk": chunk})
                    await asyncio.sleep(0.02)
                async with _lock:
                    append_chat_conversation("assistant", reply)
                    state_payload = _get_state().model_dump()

            elif intent == "advance_month":
                async with _lock:
                    current_state = _get_state()
                    blocking_event = _find_blocking_event(current_state)
                    if blocking_event is not None:
                        yield _sse_event("error", {
                            "status": 409,
                            "detail": _blocking_event_error_detail(blocking_event),
                        })
                        return

                    before_state = current_state.model_copy(deep=True)
                    state = before_state.model_copy(deep=True)
                    provider_for_month = _get_provider()

                    new_ministers_raw = prepare_month_advance(state)
                    script_decisions = await _decide_script_triggers_for_state(provider_for_month, state)
                    triggered_events_raw, game_over = finalize_month_advance(
                        state,
                        script_trigger_decisions=script_decisions,
                    )
                    new_ministers = [str(name) for name in new_ministers_raw if isinstance(name, str)]
                    triggered_events = [str(name) for name in triggered_events_raw if isinstance(name, str)]
                    _set_state(state)

                    delta = _state_delta(before_state, state)
                    effects_applied = _has_effects(delta)
                    reply = f"陛下，已入{state.time.year}年{state.time.month}月。"
                    if new_ministers:
                        reply += f" 新入朝臣：{'、'.join(new_ministers)}。"
                    if triggered_events:
                        reply += f" 新起之事：{'、'.join(triggered_events[:4])}。"
                    append_chat_conversation("assistant", reply)
                    state_payload = state.model_dump()

                for chunk in _stream_chunks(reply):
                    yield _sse_event("narrative_chunk", {"chunk": chunk})
                    await asyncio.sleep(0.02)

            else:
                async with _lock:
                    blocking_event = _find_blocking_event(_get_state())
                if blocking_event is not None:
                    yield _sse_event("error", {
                        "status": 409,
                        "detail": _blocking_event_error_detail(blocking_event),
                    })
                    return

                response = await execute_decree(DecreeRequest(free_text=message))
                reply = str(response.get("narrative", "")).strip() or "陛下，旨意已行。"
                minister_reactions = _normalize_minister_reactions(response.get("minister_reactions"))
                raw_delta = response.get("delta")
                if isinstance(raw_delta, dict):
                    for key, value in raw_delta.items():
                        if isinstance(value, bool):
                            continue
                        if isinstance(value, (int, float)) and value != 0:
                            delta[str(key)] = value
                effects_applied = _has_effects(delta)

                for chunk in _stream_chunks(reply):
                    yield _sse_event("narrative_chunk", {"chunk": chunk})
                    await asyncio.sleep(0.02)

                async with _lock:
                    append_chat_conversation("assistant", reply)
                    state_payload = _get_state().model_dump()

            if effects_applied:
                yield _sse_event("effects", {
                    "delta": delta,
                    "summary": _format_effect_summary(delta),
                })
            if minister_reactions:
                yield _sse_event("reactions", {"minister_reactions": minister_reactions})

            if state_payload is None:
                async with _lock:
                    state_payload = _get_state().model_dump()

            yield _sse_event("state", {"state": state_payload})
            yield _sse_event("done", {
                "reply": reply,
                "state": state_payload,
                "effects_applied": effects_applied,
                "narrative": reply,
                "intent": intent,
                "minister_reactions": minister_reactions,
                "triggered_events": triggered_events,
                "new_ministers": new_ministers,
                "game_over": game_over,
            })
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else ErrorResponse(
                error_code="chat_http_error",
                message=str(exc.detail),
            ).model_dump()
            yield _sse_event("error", {"status": exc.status_code, "detail": detail})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield _sse_event("error", {
                "status": 500,
                "detail": ErrorResponse(
                    error_code="chat_stream_error",
                    message=f"聊天处理失败：{exc}",
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
