from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models.game import (
    GameState, Minister, StructuredDecree, DecreeResponse, HistoryEntry,
    ErrorResponse, create_initial_state, INITIAL_MINISTERS, INITIAL_FACTIONS,
)
from models.enums import DecreeType, MinisterStatus
from engine.core import process_decree, check_preconditions, validate_target
from engine.tables import FACTION_STANCE
from ai.provider import PARSE_ERROR_TYPE_UNAVAILABLE, MockProvider, get_provider
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


# ── Request / Response models ───────────────────────────

class DecreeRequest(BaseModel):
    decrees: list[StructuredDecree]
    source_script_id: str | None = None


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

@router.post("/decree")
async def execute_decree(req: DecreeRequest):
    if _lock.locked():
        raise HTTPException(409, detail=ErrorResponse(
            error_code="decree_in_progress",
            message="正在处理上一道政令，请稍候",
        ).model_dump())

    async with _lock:
        state = _get_state()
        provider = _get_provider()

        if not req.decrees and not req.source_script_id:
            raise HTTPException(422, detail=ErrorResponse(
                error_code="invalid_decree",
                message="至少需要一道政令",
            ).model_dump())

        last_response: dict | None = None

        for decree in req.decrees:
            reason = check_preconditions(state, decree)
            if reason:
                narrative = await provider.rejection_narrative(decree, reason)
                raise HTTPException(422, detail=ErrorResponse(
                    error_code="precondition_failed",
                    message=reason,
                    details={"ai_narrative": narrative},
                ).model_dump())

            target_err = validate_target(decree)
            if target_err:
                raise HTTPException(422, detail=ErrorResponse(
                    error_code="invalid_decree",
                    message=target_err,
                ).model_dump())

            delta, attribution, triggered, game_over = process_decree(state, decree)

            narrative = await provider.generate_narrative(
                attribution, state, triggered, decree,
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
            # empty decrees (e.g. script "wait" option) — still advance turn
            delta, attribution, triggered, game_over = process_decree(state)
            narrative = "陛下暂且按兵不动，静观时局变化。"
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
            ).model_dump()

        # refresh state in response after script cleanup
        last_response["state"] = state.model_dump()
        return last_response


# ── 6.3 POST /api/decree/parse ─────────────────────────

@router.post("/decree/parse")
async def parse_decree(req: ParseRequest):
    provider = _get_provider()
    result = await provider.parse_free_input(req.text, _get_state())
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
    data = state.model_dump()
    total = len(data["history_log"])
    data["history_log"] = data["history_log"][-20:]
    data["history_total_count"] = total
    return data


# ── 6.5 GET /api/history ───────────────────────────────

@router.get("/history")
async def get_history(offset: int = 0, limit: int = 20):
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
    return {"debate_supported": supported, "portrait_supported": supported}


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
