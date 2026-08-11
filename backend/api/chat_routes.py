"""Chat-mode API routes."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ai.narrative_context import build_persisted_narrative_context
from models.game import ErrorResponse, GameEvent, GameState

from .narrative_routes import generate_contextual_narrative, record_contextual_exchange
from .routes import advance_month_endpoint, execute_decree
from .schemas import ChatRequest, DecreeRequest
from .state import (
    _get_provider,
    _get_state,
    _ensure_world_head,
    _lock,
    _split_stream_sentences,
    _sse_event,
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

    # The classifier reason is provider-authored free text. Keep it out of the
    # player-visible SSE channel and expose only a deterministic server summary.
    reason = {
        "query": "识别为局势查询",
        "execute": "识别为执行行动",
        "advance_month": "识别为推进月份",
    }[intent]
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
                current_state, _current_ref = _ensure_world_head()
                state_snapshot = current_state.model_copy(deep=True)
                history_context = build_persisted_narrative_context(
                    path_id="ordinary_chat",
                    state=state_snapshot,
                    topic_id="chat",
                    action_text=message,
                )
                history_for_model = [
                    {"role": memory.role, "content": memory.content}
                    for memory in history_context.memories
                ]

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
            narrative_status: str | None = None
            narrative_context_path_id = history_context.path_id
            narrative_path_id: str | None = None
            context_version_id = state_snapshot.world_metadata.version_id
            settlement_id = None
            narrative_artifact_id = None
            narrative_request_id: str | None = None
            narrative_progress: list[str] = []

            if intent == "query":
                yield _sse_event("progress", {
                    "stage": "context_ready",
                    "message": "已锁定当前世界与对话记忆。",
                })
                yield _sse_event("progress", {
                    "stage": "generating",
                    "message": "正在生成完整回复，模型原文不会直接展示。",
                })
                narrative_result = await generate_contextual_narrative(
                    state=state_snapshot,
                    path_id="chat_sse",
                    topic_id="chat",
                    action_text=message,
                )
                reply = narrative_result.text
                narrative_status = narrative_result.narrative_status
                narrative_path_id = narrative_result.path_id
                context_version_id = narrative_result.context_version_id
                settlement_id = narrative_result.settlement_id
                narrative_artifact_id = narrative_result.artifact_id
                narrative_request_id = narrative_result.request_id
                narrative_progress = list(narrative_result.progress_stages)
                yield _sse_event("progress", {
                    "stage": "validating",
                    "message": "正在核对当前世界与已提交事实。",
                })
                yield _sse_event("progress", {
                    "stage": "validated",
                    "message": "回复已完成事实校验，正在呈现……",
                })
                for chunk in _stream_chunks(reply):
                    yield _sse_event("narrative_chunk", {"chunk": chunk})
                    await asyncio.sleep(0.02)
                async with _lock:
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

                yield _sse_event("progress", {
                    "stage": "context_ready",
                    "message": "已锁定当前世界与月份上下文。",
                })
                yield _sse_event("progress", {
                    "stage": "generating",
                    "message": "正在裁决月份推进并生成完整回复。",
                })
                month_result = await advance_month_endpoint()
                state = GameState.model_validate(month_result["state"])
                month_narrative = month_result["narrative"]
                if hasattr(month_narrative, "model_dump"):
                    month_narrative = month_narrative.model_dump()
                new_ministers = [
                    str(item.get("name"))
                    for item in month_result["new_ministers"]
                    if isinstance(item, dict) and item.get("name")
                ]
                triggered_events = [str(name) for name in month_result["triggered_events"]]
                game_over = month_result["game_over"]
                async with _lock:
                    delta = _state_delta(before_state, state)
                    effects_applied = _has_effects(delta)
                    reply = str(month_narrative["text"])
                    narrative_status = month_narrative["narrative_status"]
                    narrative_path_id = month_narrative["path_id"]
                    context_version_id = month_narrative["context_version_id"]
                    settlement_id = month_narrative["settlement_id"]
                    narrative_artifact_id = month_narrative["artifact_id"]
                    narrative_request_id = month_narrative["request_id"]
                    narrative_progress = list(month_narrative["progress_stages"])
                    record_contextual_exchange(
                        state=state,
                        path_id="chat_sse",
                        topic_id="chat",
                        user_text=message,
                        assistant_text=reply,
                        request_id=narrative_request_id,
                        settlement_id=settlement_id,
                    )
                    state_payload = state.model_dump()

                yield _sse_event("progress", {
                    "stage": "validating",
                    "message": "正在核对月份结算与当前事实。",
                })
                yield _sse_event("progress", {
                    "stage": "validated",
                    "message": "回复已完成事实校验，正在呈现……",
                })
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

                yield _sse_event("progress", {
                    "stage": "context_ready",
                    "message": "已锁定当前世界与行动上下文。",
                })
                yield _sse_event("progress", {
                    "stage": "generating",
                    "message": "正在结算行动并生成完整回复。",
                })
                response = await execute_decree(DecreeRequest(free_text=message))
                reply = str(response.get("narrative", "")).strip() or "主公，旨意已行。"
                narrative_status = response.get("narrative_status")
                narrative_path_id = response.get("narrative_path_id")
                context_version_id = response.get("state", {}).get("world_metadata", {}).get(
                    "version_id",
                    context_version_id,
                )
                settlement_id = response.get("settlement_id")
                narrative_artifact_id = response.get("narrative_artifact_id")
                narrative_request_id = response.get("narrative_request_id")
                narrative_progress = list(response.get("narrative_progress") or [])
                minister_reactions = _normalize_minister_reactions(response.get("minister_reactions"))
                raw_delta = response.get("delta")
                if isinstance(raw_delta, dict):
                    for key, value in raw_delta.items():
                        if isinstance(value, bool):
                            continue
                        if isinstance(value, (int, float)) and value != 0:
                            delta[str(key)] = value
                effects_applied = _has_effects(delta)

                yield _sse_event("progress", {
                    "stage": "validating",
                    "message": "正在核对行动结算与当前事实。",
                })
                yield _sse_event("progress", {
                    "stage": "validated",
                    "message": "回复已完成事实校验，正在呈现……",
                })
                for chunk in _stream_chunks(reply):
                    yield _sse_event("narrative_chunk", {"chunk": chunk})
                    await asyncio.sleep(0.02)

                async with _lock:
                    current_state = _get_state()
                    state_payload = current_state.model_dump()
                    if narrative_request_id:
                        record_contextual_exchange(
                            state=current_state,
                            path_id="chat_sse",
                            topic_id="chat",
                            user_text=message,
                            assistant_text=reply,
                            request_id=narrative_request_id,
                            settlement_id=settlement_id,
                        )

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
                "narrative_status": narrative_status,
                "narrative_context_path_id": narrative_context_path_id,
                "narrative_path_id": narrative_path_id,
                "context_version_id": context_version_id,
                "settlement_id": settlement_id,
                "narrative_artifact_id": narrative_artifact_id,
                "narrative_request_id": narrative_request_id,
                "narrative_progress": narrative_progress,
            })
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else ErrorResponse(
                error_code="chat_http_error",
                message=str(exc.detail),
            ).model_dump()
            yield _sse_event("error", {"status": exc.status_code, "detail": detail})
        except asyncio.CancelledError:
            raise
        except Exception:
            yield _sse_event("error", {
                "status": 500,
                "detail": ErrorResponse(
                    error_code="chat_stream_error",
                    message="聊天处理失败，请稍后重试",
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
