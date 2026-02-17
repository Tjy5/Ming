from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models.game import (
    GameState, Minister, StructuredDecree, DecreeResponse, HistoryEntry,
    ErrorResponse, create_initial_state, INITIAL_MINISTERS, INITIAL_FACTIONS,
    CourtAssembly, AssemblyParticipant, PolicySuggestion, clamp_state,
    FreeformResult,
)
from models.enums import DecreeType, MinisterStatus, MemorialStatus
from engine.core import process_decree, check_preconditions, validate_target
from engine.tables import FACTION_STANCE
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

MAX_FREE_TEXT_LENGTH = 1000

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
    global _state
    # normalize free_text
    free_text = (req.free_text or "").strip() or None
    if free_text and len(free_text) > MAX_FREE_TEXT_LENGTH:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="invalid_decree",
            message=f"输入长度不能超过{MAX_FREE_TEXT_LENGTH}字",
        ).model_dump())
    if free_text and req.decrees:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="invalid_decree",
            message="decrees 与 free_text 不能同时提供",
        ).model_dump())
    if _lock.locked():
        raise HTTPException(409, detail=ErrorResponse(
            error_code="decree_in_progress",
            message="正在处理上一道政令，请稍候",
        ).model_dump())

    async with _lock:
        state = _get_state().model_copy(deep=True)
        provider = _get_provider()

        # script state_effects: apply BEFORE decrees
        if req.state_effects:
            _apply_state_effects(state, req.state_effects)

        last_response: dict | None = None

        # ── Freeform path: free_text provided, no structured decrees ──
        if free_text and not req.decrees:
            freeform = await provider.process_freeform(free_text, state)

            if isinstance(freeform, FreeformResult):
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
            for decree in req.decrees:
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

                narrative = await provider.generate_narrative(
                    attribution, state, triggered, decree,
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

        # refresh state in response after script cleanup
        last_response["state"] = state.model_dump()
        return last_response


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

        provider = _get_provider()
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
        return DecreeResponse(
            state=state, delta=delta, attribution=attr,
            narrative=narrative, newly_triggered_events=triggered,
            game_time=state.time, game_over=game_over,
            minister_reactions=reactions, turn_summary=summary,
            memorial_triggers=mem_triggers,
        ).model_dump()


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
