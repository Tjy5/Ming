"""Court assembly endpoints."""
from __future__ import annotations

import logging
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, HTTPException

from models.game import (
    StructuredDecree, DecreeResponse,
    ErrorResponse, CourtAssembly, AssemblyParticipant,
    PolicySuggestion, SuggestionRationaleFactor,
    AssemblyPetition, AssemblySpeech, AssemblyVote,
    HistoryEntry, Memorial, clamp_state,
)
from models.enums import DecreeType, AssemblyPhase
from engine.core import process_decree, check_preconditions, validate_target
from ai.provider import infer_decree_type_from_topic
from db import worlds
from engine.tables import FACTION_STANCE
from .action_service import ActionAdjudicationError
from .narrative_routes import generate_committed_narrative
from .schemas import (
    AdoptSuggestionRequest,
    AssemblyDebateRequest,
    AssemblyDecreeRequest,
    AssemblyDecreeResponse,
    AssemblyRageRequest,
    AssemblyVoteRequest,
    ConveneAssemblyRequest,
    DecreeRequest,
)
from .assembly_helpers import (
    MIN_PARTICIPANTS as _ASSEMBLY_MIN_PARTICIPANTS,
    normalize_speech_stance as _normalize_speech_stance,
    normalize_vote_choice as _normalize_vote_choice,
    require_assembly as _require_assembly,
    resolve_assembly_ministers as _resolve_assembly_ministers,
    select_assembly_actor_views,
    time_to_months as _time_to_months,
)
from .continuity_service import ensure_governance_continuity
from .state import (
    _get_provider,
    _get_state,
    _ensure_world_head,
    _lock,
    _settle_state,
)

assembly_router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def _suggestion_id(*, state, topic: str, index: int, decree_type: DecreeType) -> str:
    metadata = state.world_metadata
    identity = ":".join((
        str(metadata.game_id),
        str(metadata.branch_id),
        str(metadata.version_id),
        topic.strip(),
        str(index),
        decree_type.value,
    ))
    return uuid5(NAMESPACE_URL, f"mingchao-assembly-suggestion:{identity}").hex


def _suggestion_rationale(
    *,
    state,
    topic: str,
    decree_type: DecreeType,
    supporter_names: list[str],
) -> list[SuggestionRationaleFactor]:
    metadata = state.world_metadata
    factors = [
        SuggestionRationaleFactor(
            fact_reference=f"version:{metadata.version_id}",
            label="来源版本",
            value=str(metadata.version_id),
        ),
        SuggestionRationaleFactor(
            fact_reference="assembly:topic",
            label="当前议题",
            value=topic.strip(),
        ),
        SuggestionRationaleFactor(
            fact_reference=f"decree-type:{decree_type.value}",
            label="政令类型",
            value=decree_type.value,
        ),
    ]
    current_requirements = {
        DecreeType.TAX_INCREASE: [
            ("state:civil_morale", "当前民心", state.civil_morale),
        ],
        DecreeType.TAX_DECREASE: [
            ("state:national_treasury", "当前国库", state.national_treasury),
        ],
        DecreeType.RECRUIT_TROOPS: [
            ("state:national_treasury", "当前国库", state.national_treasury),
            ("state:population", "当前人口", state.population),
        ],
        DecreeType.DISBAND_TROOPS: [
            ("state:military_strength", "当前兵力", state.military_strength),
        ],
        DecreeType.PERSONNEL: [
            ("state:court_prestige", "当前威望", state.court_prestige),
        ],
        DecreeType.DIPLOMACY: [
            ("state:national_treasury", "当前国库", state.national_treasury),
        ],
        DecreeType.DISASTER_RELIEF: [
            ("state:national_treasury", "当前国库", state.national_treasury),
            ("state:grain", "当前粮草", state.grain),
        ],
        DecreeType.HARSH_PUNISHMENT: [
            ("state:court_prestige", "当前威望", state.court_prestige),
        ],
    }
    factors.extend(
        SuggestionRationaleFactor(
            fact_reference=fact_reference,
            label=label,
            value=str(value),
        )
        for fact_reference, label, value in current_requirements[decree_type]
    )
    entity_by_name = {
        entity.display_name: entity
        for entity in state.entity_registry.values()
    }
    for name in supporter_names:
        entity = entity_by_name.get(name)
        if entity is None:
            continue
        factors.append(SuggestionRationaleFactor(
            fact_reference=f"entity:{entity.entity_id}:availability",
            label="当前在朝支持者",
            value=name,
        ))
    return factors


def _active_suggestion_supporters(state, supporter_names: list[str]) -> list[str]:
    """Keep only supporters that are still active, available world entities."""

    entity_by_name = {
        entity.display_name: entity
        for entity in state.entity_registry.values()
    }
    return [
        name
        for name in supporter_names
        if (
            (entity := entity_by_name.get(name)) is not None
            and entity.status == "active"
            and entity.available
        )
    ]


def _build_policy_suggestions(
    *,
    state,
    topic: str,
    default_decree_type: DecreeType,
    participant_names: set[str],
    raw_suggestions: list[object],
) -> list[PolicySuggestion]:
    """Normalize provider/stance candidates into safe, versioned player options."""

    suggestions: list[PolicySuggestion] = []
    for index, raw in enumerate(raw_suggestions[:3], start=1):
        if not isinstance(raw, dict):
            continue
        try:
            decree_type = DecreeType(raw.get("decree_type", default_decree_type.value))
        except (ValueError, TypeError):
            decree_type = default_decree_type
        raw_names = raw.get("supporter_names", [])
        supporter_names = (
            [
                name for name in raw_names
                if isinstance(name, str) and name in participant_names
            ]
            if isinstance(raw_names, list) else []
        )
        metadata = state.world_metadata
        suggestions.append(PolicySuggestion(
            title=f"朝议方案{index}",
            description="这是行动建议而非结果承诺；提交后将依据当前世界重新结算。",
            related_decree=StructuredDecree(type=decree_type),
            supporter_names=supporter_names,
            suggestion_id=_suggestion_id(
                state=state,
                topic=topic,
                index=index,
                decree_type=decree_type,
            ),
            source_game_id=metadata.game_id,
            source_branch_id=metadata.branch_id,
            source_version_id=metadata.version_id,
            rationale_factors=_suggestion_rationale(
                state=state,
                topic=topic,
                decree_type=decree_type,
                supporter_names=supporter_names,
            ),
        ))
    return suggestions


def _suggestion_source_is_visible(suggestion: PolicySuggestion, state) -> bool:
    """Accept only a source version on the current version's ancestry chain."""

    if suggestion.source_version_id is None:
        return True  # additive compatibility for legacy saves
    metadata = state.world_metadata
    if metadata.game_id is None or metadata.version_id is None:
        return False
    if suggestion.source_game_id not in {None, metadata.game_id}:
        return False
    cursor = metadata.version_id
    seen = set()
    while cursor is not None and cursor not in seen:
        if cursor == suggestion.source_version_id:
            try:
                source = worlds.load_version(cursor)
            except worlds.WorldStoreError:
                return False
            return (
                source.ref.game_id == metadata.game_id
                and suggestion.source_branch_id in {None, source.ref.branch_id}
            )
        seen.add(cursor)
        try:
            cursor = worlds.load_version(cursor).ref.parent_version_id
        except worlds.WorldStoreError:
            return False
    return False


# ── POST /api/assembly/start ────────────────────────────

@assembly_router.post("/assembly/start")
async def assembly_start():
    async with _lock:
        current_state, _current_ref = _ensure_world_head()
        # A committed world may have lost every pre-seeded minister. Resolve
        # that vacuum through the normal settlement pipeline before applying
        # the assembly action, so this public path remains playable.
        continuity_state = ensure_governance_continuity()
        if continuity_state is not None:
            current_state = continuity_state
        state = current_state.model_copy(deep=True)
        current_month = _time_to_months(state.time.year, state.time.month)
        if state.last_assembly_month >= current_month:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="assembly_cooldown",
                message="本月已召开过朝会",
            ).model_dump())
        participant_views = select_assembly_actor_views(state)
        if len(participant_views) < _ASSEMBLY_MIN_PARTICIPANTS and continuity_state is None:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="insufficient_ministers",
                message="在朝大臣不足，无法召开朝会",
            ).model_dump())
        state.last_assembly = CourtAssembly(
            phase=AssemblyPhase.PETITION,
            participants=[
                AssemblyParticipant(
                    name=actor.minister.name,
                    faction=actor.minister.faction,
                    position=(
                        actor.minister.positions[0]
                        if actor.minister.positions else "参议主体"
                    ),
                    argument_text="",
                    entity_id=actor.entity_id,
                    entity_type=actor.entity_type,
                    capabilities=list(actor.capabilities),
                    capability_sources=list(actor.capability_sources),
                )
                for actor in participant_views
            ],
        )
        state.last_assembly_month = current_month
        state, settlement_result = await _settle_state(
            state,
            action_kind="assembly_start",
            raw_text="召开朝会",
        )
        response = state.last_assembly.model_dump()
        response.update({
            "settlement_id": settlement_result.facts.settlement_id,
            "context_version_id": settlement_result.version.version_id,
        })
        return response


# ── POST /api/assembly/petition ─────────────────────────

@assembly_router.post("/assembly/petition")
async def assembly_petition():
    async with _lock:
        current_state, _current_ref = _ensure_world_head()
        continuity_state = ensure_governance_continuity()
        if continuity_state is not None:
            current_state = continuity_state
        state = current_state.model_copy(deep=True)
        assembly = _require_assembly(state, {AssemblyPhase.PETITION})
        ministers = _resolve_assembly_ministers(state, assembly)
        petitions: list[AssemblyPetition] = []
        for m in ministers:
            petitions.append(AssemblyPetition(
                minister_name=m.name,
                content=f"臣{m.name}谨奏：{m.faction}所忧政务，望主公裁断。",
                urgency="中",
            ))
        assembly.petitions = petitions
        state, settlement_result = await _settle_state(
            state,
            action_kind="assembly_petition",
            raw_text="听取朝会奏陈",
        )
        response = state.last_assembly.model_dump()
        response.update({
            "settlement_id": settlement_result.facts.settlement_id,
            "context_version_id": settlement_result.version.version_id,
        })
        return response


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
        state = _get_state().model_copy(deep=True)
        assembly = _require_assembly(state, {AssemblyPhase.PETITION, AssemblyPhase.DEBATE})
        ministers = _resolve_assembly_ministers(state, assembly)
        provider = _get_provider()
        raw_speeches = await provider.generate_debate_speeches(topic, ministers, state)
        # Provider output is available and can now be normalized against a
        # durable parent version. Rebase the local copy because legacy callers
        # may have seeded only the compatibility state slot.
        current_state, _current_ref = _ensure_world_head()
        state = current_state.model_copy(deep=True)
        assembly = _require_assembly(state, {AssemblyPhase.PETITION, AssemblyPhase.DEBATE})
        ministers = _resolve_assembly_ministers(state, assembly)
        speeches: list[AssemblySpeech] = []
        by_name = {m.name: m for m in ministers}
        for item in raw_speeches:
            if not isinstance(item, dict):
                continue
            minister_name = str(item.get("minister_name", "")).strip()
            minister = by_name.get(minister_name)
            if minister is None:
                continue
            if minister.faction in assembly.silenced_factions:
                continue
            speeches.append(AssemblySpeech(
                minister_name=minister_name,
                # Provider output may select a stance, but it cannot rewrite
                # the committed identity/faction of a registered participant.
                faction=minister.faction,
                content="",
                stance=_normalize_speech_stance(str(item.get("stance", "中立"))),
            ))
        existing = {s.minister_name for s in speeches}
        for m in ministers:
            if m.name in existing or m.faction in assembly.silenced_factions:
                continue
            speeches.append(AssemblySpeech(
                minister_name=m.name,
                faction=m.faction,
                content="",
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
            assembly.decree_type = infer_decree_type_from_topic(topic) or DecreeType.PERSONNEL

        assembly.phase = AssemblyPhase.DEBATE
        assembly.current_topic = topic
        assembly.topic = topic
        assembly.speeches = speeches
        if assembly.decree_type is not None:
            supporter_names = [
                speech.minister_name
                for speech in speeches
                if speech.stance == "赞成"
            ]
            assembly.suggestions = _build_policy_suggestions(
                state=state,
                topic=topic,
                default_decree_type=assembly.decree_type,
                participant_names={minister.name for minister in ministers},
                raw_suggestions=[{
                    "decree_type": assembly.decree_type.value,
                    "supporter_names": supporter_names,
                }],
            )
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
        assembly.debate_text = ""
        try:
            state, settlement_result = await _settle_state(
                state,
                action_kind="assembly_debate",
                raw_text=topic,
                key_factors=[
                    f"赞成{support_count}人",
                    f"反对{oppose_count}人",
                    f"共识：{assembly.consensus}",
                ],
            )
        except ActionAdjudicationError as exc:
            raise HTTPException(
                503,
                detail=ErrorResponse(error_code=exc.code, message=exc.message).model_dump(),
            ) from None
        narrative_result = await generate_committed_narrative(
            state=state,
            facts=settlement_result.facts,
            path_id="assembly_debate",
            topic_id=f"assembly:{topic}",
            action_text=topic,
            reuse_current=settlement_result.replayed,
        )
        response = state.last_assembly.model_dump()
        response.update({
            "debate_text": narrative_result.text,
            "narrative_status": narrative_result.narrative_status,
            "narrative_path_id": narrative_result.path_id,
            "settlement_id": narrative_result.settlement_id,
            "context_version_id": narrative_result.context_version_id,
            "narrative_artifact_id": narrative_result.artifact_id,
            "narrative_request_id": narrative_result.request_id,
            "narrative_progress": narrative_result.progress_stages,
        })
        return response


# ── POST /api/assembly/vote ─────────────────────────────

def _vote_reason(m, stance: str, decree_type) -> str:
    """08-07-minister-agent-enhancement：按八维 + 派系立场生成的差异化投票理由。"""
    a = m.abilities
    reasons = []
    if stance == "赞成":
        if a.military >= 70 and m.ambition >= 50:
            reasons.append("臣以为当以兵威定之，迟则生变")
        elif a.civil >= 70 and m.ambition < 40:
            reasons.append("内政稳固，行之有利")
        elif m.ambition >= 70:
            reasons.append("此乃扩势良机，不可失")
        else:
            reasons.append("于国于民，利大于弊")
    elif stance == "反对":
        if m.corruption < 30:
            reasons.append("用度当惜，勿加重民赋")
        elif m.loyalty < 40:
            reasons.append("此举恐损根基，宜缓")
        elif a.military < 40 and decree_type in (DecreeType.RECRUIT_TROOPS, DecreeType.DISBAND_TROOPS):
            reasons.append("兵事非所长，恐难竟功")
        else:
            reasons.append("弊多利少，不宜轻动")
    else:  # 弃权
        if m.ambition >= 70:
            reasons.append("风头不便，且观后效")
        else:
            reasons.append("利弊相当，未敢轻断")
    # 派系立场强化
    fs = FACTION_STANCE.get(m.faction, {}).get(decree_type.value if hasattr(decree_type, "value") else decree_type, 0)
    if fs >= 8:
        reasons.append(f"{m.faction}之利，自当力挺")
    elif fs <= -8:
        reasons.append(f"有违{m.faction}根本，难以苟同")
    return "；".join(reasons)


@assembly_router.post("/assembly/vote")
async def assembly_vote(req: AssemblyVoteRequest):
    async with _lock:
        state = _get_state().model_copy(deep=True)
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
                reason=_vote_reason(m, vote, decree_type),
            ))
        assembly.phase = AssemblyPhase.VOTE
        assembly.votes = votes
        support_count = sum(1 for v in votes if v.vote == "赞成")
        oppose_count = sum(1 for v in votes if v.vote == "反对")
        abstain_count = sum(1 for v in votes if v.vote == "弃权")
        state, settlement_result = await _settle_state(
            state,
            action_kind="assembly_vote",
            raw_text=assembly.current_topic or assembly.topic or "朝会表决",
        )
        return {
            "assembly": state.last_assembly.model_dump(),
            "support_count": support_count,
            "oppose_count": oppose_count,
            "abstain_count": abstain_count,
            "settlement_id": settlement_result.facts.settlement_id,
            "context_version_id": settlement_result.version.version_id,
        }


# ── POST /api/assembly/decree ───────────────────────────

@assembly_router.post("/assembly/decree", response_model=AssemblyDecreeResponse)
async def assembly_decree(req: AssemblyDecreeRequest):
    decision = (req.decision or "").strip().lower()
    if decision not in {"adopt", "override", "dismiss"}:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="invalid_decision",
            message="decision 仅支持 adopt/override/dismiss",
        ).model_dump())
    async with _lock:
        state = _get_state().model_copy(deep=True)
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
                logger.error(
                    "Assembly decree execution failed: exception_type=%s",
                    type(e).__name__,
                )

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
        state, settlement_result = await _settle_state(
            state,
            action_kind="assembly_decree",
            raw_text=f"朝会裁断：{decision}",
        )
        result = {
            "state": state.model_dump(),
            "assembly": state.last_assembly.model_dump(),
            "majority_vote": majority_vote,
            "vote_counts": vote_counts,
            "faction_changes": faction_changes,
            "settlement_id": settlement_result.facts.settlement_id,
            "context_version_id": settlement_result.version.version_id,
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
        state = _get_state().model_copy(deep=True)
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
        state, settlement_result = await _settle_state(
            state,
            action_kind="assembly_rage",
            raw_text=f"龙颜大怒，喝止{target_faction}",
        )
        return {
            "state": state.model_dump(),
            "assembly": state.last_assembly.model_dump(),
            "effects": faction_effects,
            "settlement_id": settlement_result.facts.settlement_id,
            "context_version_id": settlement_result.version.version_id,
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
        current_state, _current_ref = _ensure_world_head()
        continuity_state = ensure_governance_continuity()
        state = (continuity_state or current_state).model_copy(deep=True)
        current_month = _time_to_months(state.time.year, state.time.month)

        if state.last_assembly_month >= current_month:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="assembly_cooldown",
                message="本月已召开过朝会，每月最多1次",
            ).model_dump())

        participant_views = select_assembly_actor_views(state)
        participants = [actor.minister for actor in participant_views]
        if len(participant_views) < 3 and continuity_state is None:
            raise HTTPException(400, detail=ErrorResponse(
                error_code="insufficient_ministers",
                message="在朝大臣不足，无法召开朝会",
            ).model_dump())

        provider = _get_provider()
        ai_result = await provider.generate_assembly_debate(req.topic, participants, state)
        ai = ai_result if isinstance(ai_result, dict) else {}

        # Provider/schema gating happens before a first durable root is created.
        # Once the provider result is safely normalized, build candidate evidence
        # from the committed parent version that the assembly will settle from.
        current_state, _current_ref = _ensure_world_head()
        state = current_state.model_copy(deep=True)

        assembly = CourtAssembly(
            phase=AssemblyPhase.DEBATE,
            topic=req.topic,
            current_topic=req.topic,
            decree_type=decree_type,
            participants=[
                AssemblyParticipant(
                    name=actor.minister.name,
                    faction=actor.minister.faction,
                    position=(
                        actor.minister.positions[0]
                        if actor.minister.positions else "参议主体"
                    ),
                    argument_text="",
                    entity_id=actor.entity_id,
                    entity_type=actor.entity_type,
                    capabilities=list(actor.capabilities),
                    capability_sources=list(actor.capability_sources),
                )
                for actor in participant_views
            ],
            debate_text="",
            consensus=(
                str(ai.get("consensus"))
                if str(ai.get("consensus")) in {"support", "oppose", "divided"}
                else "divided"
            ),
        )

        raw_suggestions = ai.get("suggestions")
        if isinstance(raw_suggestions, list):
            assembly.suggestions = _build_policy_suggestions(
                state=state,
                topic=req.topic,
                default_decree_type=decree_type,
                participant_names={participant.name for participant in participants},
                raw_suggestions=raw_suggestions,
            )

        state.last_assembly = assembly
        state.last_assembly_month = current_month
        state, settlement_result = await _settle_state(
            state,
            action_kind="court_assembly_convene",
            raw_text=req.topic,
        )
        narrative_result = await generate_committed_narrative(
            state=state,
            facts=settlement_result.facts,
            path_id="assembly_debate",
            topic_id=f"assembly:{req.topic}",
            action_text=req.topic,
            reuse_current=settlement_result.replayed,
        )

    response = state.last_assembly.model_dump()
    response.update({
        "debate_text": narrative_result.text,
        "narrative_status": narrative_result.narrative_status,
        "narrative_path_id": narrative_result.path_id,
        "settlement_id": narrative_result.settlement_id,
        "context_version_id": narrative_result.context_version_id,
        "narrative_artifact_id": narrative_result.artifact_id,
        "narrative_request_id": narrative_result.request_id,
        "narrative_progress": narrative_result.progress_stages,
    })
    return response


# ── Legacy: POST /api/court-assembly/adopt ───────────────

@assembly_router.post("/court-assembly/adopt")
async def adopt_suggestion(req: AdoptSuggestionRequest):
    if req.mode == "free_input":
        free_text = (req.free_text or "").strip()
        if not free_text:
            raise HTTPException(422, detail=ErrorResponse(
                error_code="free_text_required",
                message="自由输入不能为空",
            ).model_dump())
        # Reuse the canonical freeform adjudication path. Import lazily to avoid
        # widening the assembly module's import cycle during application startup.
        from .routes import execute_decree

        response = await execute_decree(DecreeRequest(free_text=free_text))
        if hasattr(response, "model_dump"):
            response = response.model_dump()
        response.update({
            "suggestion_adoption_mode": "free_input",
            "suggestion_id": None,
            "suggestion_source_version_id": None,
            "suggestion_evaluation_version_id": None,
            "suggestion_was_stale": False,
            "suggestion_rationale_factors": [],
        })
        return response

    if req.suggestion_index is None:
        raise HTTPException(422, detail=ErrorResponse(
            error_code="suggestion_index_required",
            message="原样或编辑采用必须指定候选方案",
        ).model_dump())
    if req.mode == "edited" and not (req.edited_text or "").strip():
        raise HTTPException(422, detail=ErrorResponse(
            error_code="edited_text_required",
            message="编辑采用必须提供新的行动意图",
        ).model_dump())

    mem_triggers: list[Memorial] = []

    async with _lock:
        state = _get_state().model_copy(deep=True)
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
        if req.suggestion_id is not None and req.suggestion_id != suggestion.suggestion_id:
            raise HTTPException(409, detail=ErrorResponse(
                error_code="suggestion_provenance_mismatch",
                message="候选方案标识已变化，请刷新后重试",
            ).model_dump())
        if (
            req.source_version_id is not None
            and req.source_version_id != suggestion.source_version_id
        ):
            raise HTTPException(409, detail=ErrorResponse(
                error_code="suggestion_provenance_mismatch",
                message="候选方案来源版本已变化，请刷新后重试",
            ).model_dump())
        if not _suggestion_source_is_visible(suggestion, state):
            raise HTTPException(409, detail=ErrorResponse(
                error_code="stale_suggestion_source",
                message="候选方案来源不属于当前世界线，请按当前局势重新召开朝议",
            ).model_dump())
        decree = suggestion.related_decree
        current_version_id = state.world_metadata.version_id
        suggestion_was_stale = (
            suggestion.source_version_id is not None
            and suggestion.source_version_id != current_version_id
        )
        current_supporter_names = _active_suggestion_supporters(
            state,
            suggestion.supporter_names,
        )
        current_rationale_factors = _suggestion_rationale(
            state=state,
            topic=state.last_assembly.topic,
            decree_type=decree.type,
            supporter_names=current_supporter_names,
        )

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
        state.history_log.append(HistoryEntry(
            year=state.time.year, month=state.time.month,
            decree_type=decree.type.value, decree_desc=decree.target or "",
            delta=delta, narrative="",
        ))
        action_text = (
            (req.edited_text or "").strip()
            if req.mode == "edited"
            else suggestion.title or decree.type.value
        )
        state, settlement_result = await _settle_state(
            state,
            action_kind="court_assembly_adopt",
            raw_text=action_text,
        )
        narrative_result = await generate_committed_narrative(
            state=state,
            facts=settlement_result.facts,
            path_id="structured_action",
            topic_id="assembly-adopt",
            action_text=action_text,
            reuse_current=settlement_result.replayed,
        )
        if summary:
            summary.commentary = narrative_result.text
        resp = DecreeResponse(
            state=state, delta=delta, attribution=attr,
            narrative=narrative_result.text, newly_triggered_events=triggered,
            game_time=state.time, game_over=game_over,
            minister_reactions=reactions, turn_summary=summary,
            memorial_triggers=mem_triggers,
            narrative_status=narrative_result.narrative_status,
            narrative_path_id=narrative_result.path_id,
            settlement_id=narrative_result.settlement_id,
            context_version_id=narrative_result.context_version_id,
            narrative_artifact_id=narrative_result.artifact_id,
            narrative_request_id=narrative_result.request_id,
            narrative_progress=narrative_result.progress_stages,
        ).model_dump()

    if mem_triggers:
        resp["memorial_triggers"] = [m.model_dump() for m in mem_triggers]
    resp["state"] = state.model_dump()
    resp["game_time"] = state.time.model_dump()
    resp["suggestion_id"] = suggestion.suggestion_id
    resp["suggestion_source_version_id"] = (
        str(suggestion.source_version_id) if suggestion.source_version_id else None
    )
    resp["suggestion_was_stale"] = suggestion_was_stale
    resp["suggestion_adoption_mode"] = req.mode
    resp["suggestion_evaluation_version_id"] = (
        str(current_version_id) if current_version_id else None
    )
    resp["suggestion_rationale_factors"] = [
        factor.model_dump() for factor in current_rationale_factors
    ]

    return resp


# ── Legacy: POST /api/court-assembly/silence ─────────────

@assembly_router.post("/court-assembly/silence")
async def silence_assembly():
    async with _lock:
        state = _get_state().model_copy(deep=True)
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
        state, settlement_result = await _settle_state(
            state,
            action_kind="court_assembly_silence",
            raw_text="喝止朝会",
        )
        return {
            "state": state.model_dump(),
            "prestige_change": change,
            "settlement_id": settlement_result.facts.settlement_id,
            "context_version_id": settlement_result.version.version_id,
        }
