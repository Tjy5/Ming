"""Court assembly endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models.game import (
    GameState, StructuredDecree, DecreeResponse,
    ErrorResponse, CourtAssembly, AssemblyParticipant,
    PolicySuggestion, AssemblyPetition, AssemblySpeech, AssemblyVote,
    HistoryEntry, Memorial, clamp_state,
)
from models.enums import DecreeType, AssemblyPhase
from engine.core import process_decree, check_preconditions, validate_target
from ai.provider import infer_decree_type_from_topic
from .schemas import (
    AdoptSuggestionRequest,
    AssemblyDebateRequest,
    AssemblyDecreeRequest,
    AssemblyRageRequest,
    AssemblyVoteRequest,
    ConveneAssemblyRequest,
)
from .assembly_helpers import (
    MIN_PARTICIPANTS as _ASSEMBLY_MIN_PARTICIPANTS,
    normalize_petition_urgency as _normalize_petition_urgency,
    normalize_speech_stance as _normalize_speech_stance,
    normalize_vote_choice as _normalize_vote_choice,
    require_assembly as _require_assembly,
    resolve_assembly_ministers as _resolve_assembly_ministers,
    select_assembly_participants,
    time_to_months as _time_to_months,
)
from .state import (
    _fill_memorial_content,
    _get_provider,
    _get_state,
    _lock,
)

assembly_router = APIRouter(prefix="/api")


# ── POST /api/assembly/start ────────────────────────────

@assembly_router.post("/assembly/start")
async def assembly_start():
    async with _lock:
        state = _get_state()
        current_month = _time_to_months(state.time.year, state.time.month)
        if state.last_assembly_month >= current_month:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="assembly_cooldown",
                message="本月已召开过朝会",
            ).model_dump())
        participants = select_assembly_participants(state)
        if len(participants) < _ASSEMBLY_MIN_PARTICIPANTS:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="insufficient_ministers",
                message="在朝大臣不足，无法召开朝会",
            ).model_dump())
        state.last_assembly = CourtAssembly(
            phase=AssemblyPhase.PETITION,
            participants=[
                AssemblyParticipant(
                    name=p.name,
                    faction=p.faction,
                    position=p.positions[0] if p.positions else "朝臣",
                    argument_text="",
                )
                for p in participants
            ],
        )
        state.last_assembly_month = current_month
        return state.last_assembly.model_dump()


# ── POST /api/assembly/petition ─────────────────────────

@assembly_router.post("/assembly/petition")
async def assembly_petition():
    async with _lock:
        state = _get_state()
        assembly = _require_assembly(state, {AssemblyPhase.PETITION})
        ministers = _resolve_assembly_ministers(state, assembly)
        provider = _get_provider()
        raw_petitions = await provider.generate_petitions(ministers, state)
        petitions: list[AssemblyPetition] = []
        active_names = {m.name for m in ministers}
        for item in raw_petitions:
            if not isinstance(item, dict):
                continue
            minister_name = str(item.get("minister_name", "")).strip()
            content = str(item.get("content", "")).strip()
            if minister_name not in active_names or not content:
                continue
            petitions.append(AssemblyPetition(
                minister_name=minister_name,
                content=content,
                urgency=_normalize_petition_urgency(str(item.get("urgency", "中"))),
            ))
        existing = {p.minister_name for p in petitions}
        for m in ministers:
            if m.name in existing:
                continue
            petitions.append(AssemblyPetition(
                minister_name=m.name,
                content=f"臣{m.name}谨奏：{m.faction}所忧政务，望陛下裁断。",
                urgency="中",
            ))
        assembly.petitions = petitions
        return assembly.model_dump()


# ── POST /api/assembly/debate ───────────────────────────

@assembly_router.post("/assembly/debate")
async def assembly_debate(req: AssemblyDebateRequest):
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="invalid_topic",
            message="议题不能为空",
        ).model_dump())
    async with _lock:
        state = _get_state()
        assembly = _require_assembly(state, {AssemblyPhase.PETITION, AssemblyPhase.DEBATE})
        ministers = _resolve_assembly_ministers(state, assembly)
        provider = _get_provider()
        raw_speeches = await provider.generate_debate_speeches(topic, ministers, state)
        speeches: list[AssemblySpeech] = []
        by_name = {m.name: m for m in ministers}
        for item in raw_speeches:
            if not isinstance(item, dict):
                continue
            minister_name = str(item.get("minister_name", "")).strip()
            minister = by_name.get(minister_name)
            content = str(item.get("content", "")).strip()
            if minister is None or not content:
                continue
            if minister.faction in assembly.silenced_factions:
                continue
            speeches.append(AssemblySpeech(
                minister_name=minister_name,
                faction=str(item.get("faction") or minister.faction),
                content=content,
                stance=_normalize_speech_stance(str(item.get("stance", "中立"))),
            ))
        existing = {s.minister_name for s in speeches}
        for m in ministers:
            if m.name in existing or m.faction in assembly.silenced_factions:
                continue
            speeches.append(AssemblySpeech(
                minister_name=m.name,
                faction=m.faction,
                content=f"臣{m.name}以为此议当慎行，请陛下明断。",
                stance="中立",
            ))
        if req.decree_type:
            try:
                assembly.decree_type = DecreeType(req.decree_type)
            except ValueError:
                raise HTTPException(422, detail=ErrorResponse(
                    error_code="invalid_decree_type",
                    message="无效的政令类型",
                ).model_dump())
        elif assembly.decree_type is None:
            assembly.decree_type = infer_decree_type_from_topic(topic)

        assembly.phase = AssemblyPhase.DEBATE
        assembly.current_topic = topic
        assembly.topic = topic
        assembly.speeches = speeches
        speech_map = {s.minister_name: s.content for s in speeches}
        for p in assembly.participants:
            p.argument_text = speech_map.get(p.name, p.argument_text)

        support_count = sum(1 for s in speeches if s.stance == "赞成")
        oppose_count = sum(1 for s in speeches if s.stance == "反对")
        if support_count > oppose_count:
            assembly.consensus = "support"
        elif oppose_count > support_count:
            assembly.consensus = "oppose"
        else:
            assembly.consensus = "divided"
        assembly.debate_text = "\n".join(f"{s.minister_name}：{s.content}" for s in speeches)
        return assembly.model_dump()


# ── POST /api/assembly/vote ─────────────────────────────

@assembly_router.post("/assembly/vote")
async def assembly_vote(req: AssemblyVoteRequest):
    async with _lock:
        state = _get_state()
        assembly = _require_assembly(state, {AssemblyPhase.DEBATE, AssemblyPhase.VOTE})
        ministers = _resolve_assembly_ministers(state, assembly)
        decree_type = assembly.decree_type
        if req.decree_type:
            try:
                decree_type = DecreeType(req.decree_type)
            except ValueError:
                raise HTTPException(422, detail=ErrorResponse(
                    error_code="invalid_decree_type",
                    message="无效的政令类型",
                ).model_dump())
        if decree_type is None:
            decree_type = infer_decree_type_from_topic(assembly.current_topic or assembly.topic) or DecreeType.PERSONNEL
        assembly.decree_type = decree_type
        provider = _get_provider()
        votes: list[AssemblyVote] = []
        for m in ministers:
            if m.faction in assembly.silenced_factions:
                votes.append(AssemblyVote(
                    minister_name=m.name,
                    vote="弃权",
                    reason="受龙颜大怒压制，不得置喙",
                ))
                continue
            tendency = await provider.calculate_vote_tendency(m, decree_type, state)
            vote = _normalize_vote_choice(str(tendency))
            votes.append(AssemblyVote(
                minister_name=m.name,
                vote=vote,
                reason=f"派系立场与忠诚度综合判断（忠诚度{m.loyalty}）",
            ))
        assembly.phase = AssemblyPhase.VOTE
        assembly.votes = votes
        support_count = sum(1 for v in votes if v.vote == "赞成")
        oppose_count = sum(1 for v in votes if v.vote == "反对")
        abstain_count = sum(1 for v in votes if v.vote == "弃权")
        return {
            "assembly": assembly.model_dump(),
            "support_count": support_count,
            "oppose_count": oppose_count,
            "abstain_count": abstain_count,
        }


# ── POST /api/assembly/decree ───────────────────────────

@assembly_router.post("/assembly/decree")
async def assembly_decree(req: AssemblyDecreeRequest):
    decision = (req.decision or "").strip().lower()
    if decision not in {"adopt", "override", "dismiss"}:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="invalid_decision",
            message="decision 仅支持 adopt/override/dismiss",
        ).model_dump())
    async with _lock:
        state = _get_state()
        assembly = _require_assembly(state, {AssemblyPhase.VOTE})
        vote_counts = {"赞成": 0, "反对": 0, "弃权": 0}
        for v in assembly.votes:
            if v.vote in vote_counts:
                vote_counts[v.vote] += 1
        majority_vote = max(vote_counts, key=vote_counts.get) if assembly.votes else "弃权"
        faction_changes: dict[str, int] = {}
        represented_factions = {p.faction for p in assembly.participants}

        # Execute decree if decision is adopt or override
        decree_effects = None
        if decision in {"adopt", "override"} and assembly.decree_type:
            decree = StructuredDecree(type=assembly.decree_type)
            try:
                if not check_preconditions(state, decree, enforce_monthly_limit=False):
                    decree_effects = process_decree(state, decree, mark_monthly_usage=False)
            except Exception as e:
                logging.error(f"Failed to execute decree in assembly: {e}")

        if decision == "adopt":
            if majority_vote == "赞成":
                state.court_prestige += 2
            elif majority_vote == "反对":
                state.court_prestige -= 1
        elif decision == "override":
            state.court_prestige += 3
            for f in state.factions:
                if f.name in represented_factions:
                    f.satisfaction -= 8
                    faction_changes[f.name] = -8
        else:
            state.court_prestige -= 2
            for f in state.factions:
                if f.name in represented_factions:
                    f.satisfaction -= 2
                    faction_changes[f.name] = -2

        assembly.phase = AssemblyPhase.DECREE
        assembly.final_decision = decision
        clamp_state(state)
        result = {
            "state": state.model_dump(),
            "assembly": assembly.model_dump(),
            "majority_vote": majority_vote,
            "vote_counts": vote_counts,
            "faction_changes": faction_changes,
        }
        if decree_effects:
            result["decree_effects"] = decree_effects
        return result


# ── POST /api/assembly/rage ─────────────────────────────

@assembly_router.post("/assembly/rage")
async def assembly_rage(req: AssemblyRageRequest):
    target_faction = (req.target_faction or "").strip()
    if not target_faction:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="invalid_faction",
            message="target_faction 不能为空",
        ).model_dump())
    async with _lock:
        state = _get_state()
        assembly = _require_assembly(state, {AssemblyPhase.PETITION, AssemblyPhase.DEBATE, AssemblyPhase.VOTE})
        if assembly.rage_used:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="rage_already_used",
                message="本次朝会已使用过龙颜大怒",
            ).model_dump())
        if not any(f.name == target_faction for f in state.factions):
            raise HTTPException(422, detail=ErrorResponse(
                error_code="invalid_faction",
                message="无效的派系名称",
            ).model_dump())
        assembly.rage_used = True
        assembly.silenced = True
        if target_faction not in assembly.silenced_factions:
            assembly.silenced_factions.append(target_faction)
        if assembly.speeches:
            assembly.speeches = [s for s in assembly.speeches if s.faction != target_faction]
        faction_effects: dict[str, int] = {}
        for faction in state.factions:
            delta = -10 if faction.name == target_faction else -3
            faction.satisfaction += delta
            faction_effects[faction.name] = delta
        clamp_state(state)
        return {
            "state": state.model_dump(),
            "assembly": assembly.model_dump(),
            "effects": faction_effects,
        }


# ── Legacy: POST /api/court-assembly/convene ────────────

@assembly_router.post("/court-assembly/convene")
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
            phase=AssemblyPhase.DEBATE,
            topic=req.topic,
            current_topic=req.topic,
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
            for s in ai["suggestions"][:3]:
                if not isinstance(s, dict):
                    continue
                try:
                    dt = DecreeType(s.get("decree_type", req.decree_type))
                except (ValueError, TypeError):
                    dt = decree_type
                names = s.get("supporter_names", [])
                assembly.suggestions.append(PolicySuggestion(
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

        assembly.speeches = [
            AssemblySpeech(
                minister_name=p.name,
                faction=p.faction,
                content=p.argument_text,
                stance="中立",
            )
            for p in assembly.participants if p.argument_text
        ]

        state.last_assembly = assembly
        state.last_assembly_month = current_month

    return assembly.model_dump()


# ── Legacy: POST /api/court-assembly/adopt ───────────────

@assembly_router.post("/court-assembly/adopt")
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

        reason = check_preconditions(state, decree, enforce_monthly_limit=False)
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
        delta, attr, triggered, game_over, reactions, summary = process_decree(
            state,
            decree,
            mark_monthly_usage=False,
        )
        mem_triggers = state.memorials[mem_count_before:]
        narrative = await provider.generate_narrative(attr, state, triggered, decree)
        if summary:
            ai_implications = await provider.generate_action_implications(
                {"rule_based_implications": summary.action_implications}, state,
            )
            if ai_implications:
                summary.action_implications = ai_implications
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


# ── Legacy: POST /api/court-assembly/silence ─────────────

@assembly_router.post("/court-assembly/silence")
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
