"""Post-commit narrative generation and narrative-only regeneration."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai.narrative_context import build_persisted_narrative_context
from ai.narrative_registry import NarrativePathId, get_narrative_path
from ai.narrative_service import (
    NarrativeGenerationResult,
    generate_narrative_artifact,
    result_from_artifact,
    runtime_generator,
)
from db import worlds
from db.narrative_memory import (
    NarrativeStoreConflictError,
    NarrativeStoreError,
    append_memory,
    get_current_artifact,
    init_narrative_memory_db,
)
from engine.calendar import ensure_game_time_clock
from models.game import GameState
from models.settlement import SettlementFacts
from models.world import SettlementId
from models.world import EntityId

from .state import _get_provider


narrative_router = APIRouter(prefix="/api")


class NarrativeRegenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path_id: NarrativePathId = "unified_action"
    topic_id: str = Field(default="world", min_length=1, max_length=240)

    @model_validator(mode="after")
    def _require_settlement_path(self) -> "NarrativeRegenerationRequest":
        if not get_narrative_path(self.path_id).settlement_required:
            raise ValueError("narrative regeneration requires a settlement path")
        return self


def _runtime_provider_or_none():
    try:
        return _get_provider()
    except HTTPException:
        # The settlement is already committed.  Missing/failed runtime config
        # is a narrative failure, not permission to turn the action into 409 or
        # to run a hidden rule adjudication.
        return None


def _append_result_memory(
    *,
    context,
    result: NarrativeGenerationResult,
    action_text: str | None,
) -> None:
    if context.settlement is None or result.artifact_id is None:
        return
    state_time = context.time.absolute_hour
    facts = context.settlement
    if action_text and action_text.strip():
        append_memory(
            game_id=facts.game_id,
            branch_id=facts.branch_id,
            source_version_id=facts.result_version_id,
            source_settlement_id=facts.settlement_id,
            mode=context.mode,
            phase=context.phase,
            chapter=context.chapter,
            topic_id=context.topic_id,
            person_entity_id=context.person_entity_id,
            kind="decision",
            role="user",
            content=action_text.strip(),
            created_world_hour=state_time,
            memory_id=facts.client_action_id,
        )
    append_memory(
        game_id=facts.game_id,
        branch_id=facts.branch_id,
        source_version_id=facts.result_version_id,
        source_settlement_id=facts.settlement_id,
        mode=context.mode,
        phase=context.phase,
        chapter=context.chapter,
        topic_id=context.topic_id,
        person_entity_id=context.person_entity_id,
        kind="raw_recent",
        role="assistant",
        content=result.text,
        created_world_hour=state_time,
        memory_id=result.artifact_id,
    )


def record_contextual_exchange(
    *,
    state: GameState,
    path_id: NarrativePathId,
    topic_id: str,
    user_text: str,
    assistant_text: str,
    request_id: str,
    settlement_id: SettlementId | None = None,
) -> None:
    """Persist one non-global conversation exchange at a durable world version."""

    metadata = state.world_metadata
    if (
        metadata.game_id is None
        or metadata.branch_id is None
        or metadata.version_id is None
    ):
        raise NarrativeStoreConflictError(
            "conversation memory requires a durable world version",
        )
    init_narrative_memory_db()
    path = get_narrative_path(path_id)
    world_hour = ensure_game_time_clock(state.time).absolute_hour
    normalized_topic = topic_id.strip() or "world"
    identity = request_id.strip()
    user_memory_id = uuid5(NAMESPACE_URL, f"mingchao-chat:{identity}:user")
    assistant_memory_id = uuid5(NAMESPACE_URL, f"mingchao-chat:{identity}:assistant")
    common = {
        "game_id": metadata.game_id,
        "branch_id": metadata.branch_id,
        "source_version_id": metadata.version_id,
        "source_settlement_id": settlement_id,
        "mode": path.memory_mode,
        "phase": state.phase,
        "chapter": state.chapter,
        "topic_id": normalized_topic,
        "created_world_hour": world_hour,
    }
    append_memory(
        **common,
        kind="raw_recent",
        role="user",
        content=user_text,
        memory_id=user_memory_id,
    )
    append_memory(
        **common,
        kind="raw_recent",
        role="assistant",
        content=assistant_text,
        memory_id=assistant_memory_id,
    )


async def generate_contextual_narrative(
    *,
    state: GameState,
    path_id: NarrativePathId,
    topic_id: str,
    action_text: str,
) -> NarrativeGenerationResult:
    """Generate and retain a safe narrative for a non-settlement context path."""

    init_narrative_memory_db()
    context = build_persisted_narrative_context(
        path_id=path_id,
        state=state,
        topic_id=topic_id,
        action_text=action_text,
    )
    result = await generate_narrative_artifact(
        context=context,
        state=state,
        generate=runtime_generator(_runtime_provider_or_none()),
        persist=False,
    )
    record_contextual_exchange(
        state=state,
        path_id=path_id,
        topic_id=topic_id,
        user_text=action_text,
        assistant_text=result.text,
        request_id=result.request_id,
    )
    return result


async def generate_committed_narrative(
    *,
    state: GameState,
    facts: SettlementFacts,
    path_id: NarrativePathId,
    topic_id: str,
    action_text: str | None,
    person_entity_id: EntityId | None = None,
    reuse_current: bool = False,
) -> NarrativeGenerationResult:
    # Route functions are also exercised directly outside FastAPI's startup
    # lifespan. Keep the additive schema migration on the storage boundary so
    # old saves cannot reach a path-scoped lookup with the legacy table shape.
    init_narrative_memory_db()
    current = get_current_artifact(
        facts.game_id,
        facts.branch_id,
        facts.settlement_id,
        path_id,
    )
    if reuse_current and current is not None:
        return result_from_artifact(current)
    context = build_persisted_narrative_context(
        path_id=path_id,
        state=state,
        settlement=facts,
        topic_id=topic_id,
        person_entity_id=person_entity_id,
        action_text=action_text,
    )
    provider = _runtime_provider_or_none()
    try:
        result = await generate_narrative_artifact(
            context=context,
            state=state,
            generate=runtime_generator(provider),
        )
        _append_result_memory(context=context, result=result, action_text=action_text)
        return result
    except NarrativeStoreError:
        # Storage diagnostics remain red, but the already committed player
        # action still receives a deterministic facts projection.
        return await generate_narrative_artifact(
            context=context,
            state=state,
            generate=runtime_generator(None),
            persist=False,
        )


@narrative_router.post(
    "/settlements/{settlement_id}/narrative",
    response_model=NarrativeGenerationResult,
)
async def regenerate_narrative(
    settlement_id: SettlementId,
    request: NarrativeRegenerationRequest,
) -> NarrativeGenerationResult:
    try:
        facts = worlds.get_settlement(settlement_id)
        snapshot = worlds.load_version(facts.result_version_id)
    except worlds.WorldNotFoundError as exc:
        raise HTTPException(
            404,
            detail={"error_code": exc.code, "message": exc.message},
        ) from None
    except worlds.WorldStoreError as exc:
        raise HTTPException(
            500,
            detail={"error_code": exc.code, "message": exc.message},
        ) from None
    return await generate_committed_narrative(
        state=snapshot.state,
        facts=facts,
        path_id=request.path_id,
        topic_id=request.topic_id,
        action_text=None,
        reuse_current=False,
    )
