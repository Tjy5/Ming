"""Core game routes: decrees, game lifecycle, debate, memorial, dialogue."""
from __future__ import annotations

import asyncio
import logging
import os
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from models.game import (
    GameState, StructuredDecree, DecreeResponse, HistoryEntry,
    ErrorResponse, create_initial_state,
    FreeformResult, Memorial, DialogueRequest, DialogueResponse, clamp_state,
    MemorialResolutionResult,
)
from models.enums import DecreeType, MinisterStatus, MemorialStatus
from models.positions import (
    PositionCategory, PositionInfo, POSITION_REGISTRY,
    get_positions_by_category, calculate_position_weight,
)
from engine.core import (
    check_preconditions,
    finalize_month_advance,
    get_undecided_script_trigger_candidates,
    inject_script_events,
    prepare_month_advance,
    process_decree,
    validate_target,
)
from engine.scripts import SCRIPT_REGISTRY
from ai.provider import PARSE_ERROR_TYPE_UNAVAILABLE
from .schemas import (
    DebateStartRequest,
    DecreeRequest,
    MAX_FREE_TEXT_LENGTH,
    MemorialResolveRequest,
    ParseRequest,
)
from .helpers import (
    apply_loyalty_effects as _apply_loyalty_effects,
    apply_state_effects as _apply_state_effects,
)
from .debate_helpers import (
    DEBATE_TOPICS,
    is_ai_provider as _is_ai_provider,
    select_debate_ministers,
)
from .state import (
    NarrativeChunkCallback,
    _STREAM_PROGRESS_MESSAGES,
    _MAX_DIALOGUE_MESSAGES,
    clear_chat_conversation,
    _fill_memorial_content,
    _generate_narrative_with_streaming,
    _get_provider,
    _get_state,
    _lock,
    _set_state,
    _split_stream_sentences,
    _sse_event,
    startup,
)

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def _parse_script_choice_threshold(raw: str | None) -> float:
    if raw is None:
        return 0.7
    try:
        value = float(raw.strip())
    except (TypeError, ValueError):
        return 0.7
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


SCRIPT_CHOICE_CONFIDENCE_THRESHOLD = _parse_script_choice_threshold(
    os.getenv("SCRIPT_CHOICE_CONFIDENCE_THRESHOLD"),
)


def _normalize_script_choice_result(classified: dict) -> tuple[int | None, float]:
    if "error" in classified:
        return None, 0.0
    raw_index = classified.get("choice_index")
    if raw_index is None or isinstance(raw_index, bool):
        choice_index = None
    else:
        try:
            choice_index = int(raw_index)
        except (TypeError, ValueError):
            choice_index = None

    raw_confidence = classified.get("confidence", 0.0)
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return choice_index, confidence


def _normalize_trigger_decisions(
    raw_decisions: dict,
    *,
    candidate_ids: set[str],
) -> dict[str, tuple[bool, str]]:
    normalized: dict[str, tuple[bool, str]] = {}
    for script_id in candidate_ids:
        raw_value = raw_decisions.get(script_id)
        if isinstance(raw_value, tuple) and len(raw_value) >= 2:
            normalized[script_id] = (bool(raw_value[0]), str(raw_value[1]).strip() or "AI未给出理由")
            continue
        if isinstance(raw_value, list) and len(raw_value) >= 2:
            normalized[script_id] = (bool(raw_value[0]), str(raw_value[1]).strip() or "AI未给出理由")
            continue
        if isinstance(raw_value, dict):
            normalized[script_id] = (
                bool(raw_value.get("should_trigger", True)),
                str(raw_value.get("reason", "")).strip() or "AI未给出理由",
            )
            continue
        if isinstance(raw_value, bool):
            normalized[script_id] = (raw_value, "AI未给出理由")
            continue
        normalized[script_id] = (True, "AI决策缺失，回退规则触发")
    return normalized


async def _decide_script_triggers_for_state(
    provider,
    state: GameState,
) -> dict[str, tuple[bool, str]]:
    candidates = get_undecided_script_trigger_candidates(state)
    if not candidates:
        return {}

    candidate_ids = {
        str(item.get("script_id", "")).strip()
        for item in candidates
        if isinstance(item, dict) and str(item.get("script_id", "")).strip()
    }
    if not candidate_ids:
        return {}

    raw_decisions = await provider.select_script_trigger_decisions(state, candidates)
    if not isinstance(raw_decisions, dict) or "error" in raw_decisions:
        logger.warning("Script trigger AI unavailable; fallback to rule-only mode")
        return {
            script_id: (True, "AI不可用，回退规则触发")
            for script_id in candidate_ids
        }

    return _normalize_trigger_decisions(raw_decisions, candidate_ids=candidate_ids)


# ── 6.1 POST /api/game/new ─────────────────────────────

@router.post("/game/new")
async def new_game():
    state = create_initial_state()
    provider = _get_provider()

    # Re-run initial scripted injections through AI decision path.
    state.active_events = [event for event in state.active_events if not event.is_scripted]
    state.trigger_decisions = {}
    decisions = await _decide_script_triggers_for_state(provider, state)
    inject_script_events(state, script_trigger_decisions=decisions)

    clear_chat_conversation()
    _set_state(state)
    return state.model_dump()


# ── 6.2 POST /api/decree ───────────────────────────────

async def _execute_decree_core(
    req: DecreeRequest,
    stream_narrative_callback: NarrativeChunkCallback | None = None,
) -> tuple[dict, list[Memorial], object, GameState]:
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

        last_response: dict | None = None

        # ── Freeform path: free_text provided, no structured decrees ──
        if free_text and not req.decrees:
            if req.source_script_id:
                evt = SCRIPT_REGISTRY.get(req.source_script_id)
                script_context = None
                if evt:
                    script_context = {
                        "title": evt.title,
                        "description": evt.rich_description,
                        "suggested_actions": [
                            {"label": c.label, "description": c.description}
                            for c in evt.choices
                        ],
                    }
                classified = await provider.classify_script_choice(
                    free_text,
                    script_context,
                    game_state=state,
                )
                choice_index, confidence = _normalize_script_choice_result(
                    classified if isinstance(classified, dict) else {},
                )
                if (
                    choice_index is None
                    or confidence < SCRIPT_CHOICE_CONFIDENCE_THRESHOLD
                    or not evt
                    or choice_index >= len(evt.choices)
                ):
                    raise HTTPException(422, detail=ErrorResponse(
                        error_code="FREEFORM_EMPTY",
                        message="旨意不明，请重新输入",
                    ).model_dump())

                selected_choice = evt.choices[choice_index]
                req = DecreeRequest(
                    decrees=list(selected_choice.decrees),
                    source_script_id=req.source_script_id,
                    loyalty_effects=list(selected_choice.loyalty_effects) or None,
                    state_effects=dict(selected_choice.state_effects) or None,
                )
            else:
                script_context = None
                free_text_for_history = free_text
                freeform = await provider.process_freeform(free_text_for_history, state, script_context=script_context)

                if isinstance(freeform, FreeformResult):
                    mem_count_before = len(state.memorials)
                    delta, attribution, triggered, game_over, _reactions, _summary = process_decree(
                        state, freeform=freeform,
                    )
                    _mem_triggers = state.memorials[mem_count_before:]

                    if _summary:
                        ai_implications = await provider.generate_action_implications(
                            {"rule_based_implications": _summary.action_implications}, state,
                        )
                        if ai_implications:
                            _summary.action_implications = ai_implications
                        _summary.commentary = await provider.generate_turn_commentary(
                            _summary.model_dump(), state,
                        )

                    state.history_log.append(HistoryEntry(
                        year=state.time.year, month=state.time.month,
                        decree_type="freeform",
                        decree_desc=free_text_for_history[:50],
                        delta=delta, narrative=freeform.narrative,
                    ))

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
                    parsed = await provider.parse_free_input(free_text_for_history, state)
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

        # script state_effects: only apply for verified scripted events
        if req.state_effects and req.source_script_id and req.source_script_id in SCRIPT_REGISTRY:
            _apply_state_effects(state, req.state_effects)

        # ── Structured path ──
        if last_response is None and req.decrees:
            decree_count = len(req.decrees)
            enforce_monthly_limit = req.source_script_id is None
            mark_monthly_usage = req.source_script_id is None
            for decree_index, decree in enumerate(req.decrees):
                reason = check_preconditions(
                    state,
                    decree,
                    enforce_monthly_limit=enforce_monthly_limit,
                )
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
                delta, attribution, triggered, game_over, _reactions, _summary = process_decree(
                    state,
                    decree,
                    mark_monthly_usage=mark_monthly_usage,
                )
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
                    ai_implications = await provider.generate_action_implications(
                        {"rule_based_implications": _summary.action_implications}, state,
                    )
                    if ai_implications:
                        _summary.action_implications = ai_implications
                    _summary.commentary = await provider.generate_turn_commentary(
                        _summary.model_dump(), state,
                    )

                state.history_log.append(HistoryEntry(
                    year=state.time.year, month=state.time.month,
                    decree_type=decree.type.value,
                    decree_desc=decree.target or "",
                    delta=delta, narrative=narrative,
                ))

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
                ai_implications = await provider.generate_action_implications(
                    {"rule_based_implications": _summary.action_implications}, state,
                )
                if ai_implications:
                    _summary.action_implications = ai_implications
                _summary.commentary = await provider.generate_turn_commentary(
                    _summary.model_dump(), state,
                )
            state.history_log.append(HistoryEntry(
                year=state.time.year, month=state.time.month,
                decree_type="wait", decree_desc="",
                delta=delta, narrative=narrative,
            ))
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
        _set_state(state)

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


# ── 6.3 POST /api/advance-month ───────────────────────

@router.post("/advance-month")
async def advance_month_endpoint():
    async with _lock:
        state = _get_state().model_copy(deep=True)
        provider = _get_provider()

        new_ministers = prepare_month_advance(state)
        script_decisions = await _decide_script_triggers_for_state(provider, state)
        triggered_events, game_over = finalize_month_advance(
            state,
            script_trigger_decisions=script_decisions,
        )
        _set_state(state)

    activated = [
        m.model_dump() for m in state.ministers
        if m.name in new_ministers
    ]
    return {
        "state": state.model_dump(),
        "triggered_events": triggered_events,
        "game_over": game_over,
        "new_ministers": activated,
    }


# ── 6.4 POST /api/decree/parse ─────────────────────────

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


# ── GET /api/state ──────────────────────────────────────

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


# ── GET /api/history ────────────────────────────────────

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



# ── 6.14 GET /api/ministers ────────────────────────────

@router.get("/ministers")
async def get_ministers():
    return [m.model_dump() for m in _get_state().ministers]


# ── GET /api/positions ─────────────────────────────────

@router.get("/positions")
async def get_positions(category: str | None = None):
    """Return all positions from PositionRegistry with category, weight, unique.

    Optional query param `category` filters by PositionCategory (CORE, SECONDARY, NOBLE, EUNUCH).
    """
    if category is not None:
        try:
            cat_enum = PositionCategory(category.upper())
        except ValueError:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="invalid_category",
                message=f"Invalid category: {category}. Valid: CORE, SECONDARY, NOBLE, EUNUCH",
            ).model_dump())
        names = get_positions_by_category(cat_enum)
    else:
        names = list(POSITION_REGISTRY.keys())

    result = []
    for name in names:
        info = POSITION_REGISTRY[name]
        result.append({
            "name": name,
            "category": info.category.value,
            "weight": info.weight,
            "unique": info.unique,
            "aliases": list(info.aliases),
        })
    return result


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

        narrative = ""
        accumulated_delta: dict = {}
        accumulated_reactions: list = []

        if req.action == "approved" and memorial.suggested_decrees:
            provider = _get_provider()
            last_decree = last_attr = last_triggered = None
            for decree in memorial.suggested_decrees:
                reason = check_preconditions(state, decree, enforce_monthly_limit=False)
                if reason:
                    continue
                if validate_target(decree, state):
                    continue
                delta, attr, triggered, game_over, _reactions, _summary = process_decree(
                    state,
                    decree,
                    mark_monthly_usage=False,
                )
                accumulated_reactions.extend(_reactions)
                for k, v in delta.items():
                    accumulated_delta[k] = accumulated_delta.get(k, 0) + v
                last_decree, last_attr, last_triggered = decree, attr, triggered
                state.history_log.append(HistoryEntry(
                    year=state.time.year, month=state.time.month,
                    decree_type=decree.type.value, decree_desc=decree.target or "",
                    delta=delta, narrative="",
                ))
                if game_over:
                    break
            if last_decree is not None:
                narrative = await provider.generate_narrative(last_attr, state, last_triggered, last_decree)
                state.history_log[-1].narrative = narrative

        if req.action != "approved" and narrative == "":
            if req.action == "rejected":
                narrative = f"陛下驳回了{memorial.author_name}的奏折。"
            elif req.action == "deferred":
                narrative = f"陛下将{memorial.author_name}的奏折留中待议。"

        # 为 approved 但无有效 decree 的情况补充默认叙事
        if req.action == "approved" and not narrative:
            narrative = "准奏，着即施行。"

        # 写入批复结果到 memorial.resolution_result
        memorial.resolution_result = MemorialResolutionResult(
            action=req.action,
            narrative=narrative if narrative else None,
            delta=accumulated_delta if accumulated_delta else None,
            minister_reactions=accumulated_reactions if accumulated_reactions else None
        )

        return {"state": state.model_dump(), "action": req.action, "narrative": narrative, "delta": accumulated_delta, "minister_reactions": [r.model_dump() for r in accumulated_reactions]}


# ── 6.15 POST /api/minister/{name}/dialogue ───────────

@router.post("/minister/{minister_name}/dialogue")
async def minister_dialogue(minister_name: str, req: DialogueRequest):
    async with _lock:
        state = _get_state()
        provider = _get_provider()

        minister = next((m for m in state.ministers if m.name == minister_name), None)
        if minister is None:
            raise HTTPException(404, detail=ErrorResponse(
                error_code="minister_not_found",
                message=f"大臣 {minister_name} 不存在",
            ).model_dump())

        if minister.status != MinisterStatus.ACTIVE:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="minister_not_active",
                message=f"大臣 {minister_name} 当前不在朝",
            ).model_dump())

        conversation_id = req.conversation_id or f"{minister_name}_{int(time.time())}"

        history = state.minister_conversations.setdefault(minister_name, [])
        history_for_model = [
            {"role": msg.role, "content": msg.content}
            for msg in history[-_MAX_DIALOGUE_MESSAGES:]
        ]
        history_for_model.append({"role": "user", "content": req.message})

        try:
            dialogue_result = await provider.generate_minister_dialogue(
                minister, req.message, state, history_for_model
            )

            reply = str(dialogue_result.get("reply", "")).strip()
            if not reply:
                raise ValueError("AI reply is empty")

            state.append_conversation_message(minister_name, "user", req.message)
            state.append_conversation_message(minister_name, "assistant", reply)

            raw_loyalty_change = dialogue_result.get("loyalty_change", 0)
            try:
                loyalty_change = int(raw_loyalty_change)
            except (TypeError, ValueError):
                loyalty_change = 0
            loyalty_change = max(-3, min(3, loyalty_change))

            if loyalty_change != 0:
                minister.loyalty = max(0, min(100, minister.loyalty + loyalty_change))
                clamp_state(state)

            raw_mood = str(dialogue_result.get("mood", "neutral")).strip().lower()
            mood = raw_mood if raw_mood in {"support", "neutral", "oppose"} else "neutral"

            return DialogueResponse(
                reply=reply,
                loyalty_change=loyalty_change,
                mood=mood,
                conversation_id=conversation_id,
                state=state,
            ).model_dump()

        except Exception as exc:
            raise HTTPException(503, detail=ErrorResponse(
                error_code="dialogue_generation_failed",
                message=f"对话生成失败: {exc}",
            ).model_dump())
