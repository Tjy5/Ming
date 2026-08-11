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
from models.world import BranchId, GameId, WorldVersionRef


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


class _WorldHeadCache:
    """Discardable process cache for one committed branch head.

    ``_state`` stays as the compatibility slot because existing routes and
    tests still assign it directly. A direct assignment automatically
    invalidates the durable version reference on the next facade access.
    """

    def __init__(self) -> None:
        self._published_state: GameState | None = None
        self._version_ref: WorldVersionRef | None = None

    def _synchronize_legacy_slot(self) -> None:
        if self._published_state is not _state:
            self._published_state = _state
            self._version_ref = None

    def get(self) -> GameState:
        global _state
        self._synchronize_legacy_slot()
        if _state is None:
            _state = create_initial_state()
            self._published_state = _state
        return _state

    def publish(self, state: GameState, ref: WorldVersionRef | None) -> None:
        global _state
        _state = state
        self._published_state = state
        self._version_ref = ref

    def ref(self) -> WorldVersionRef | None:
        self._synchronize_legacy_slot()
        return self._version_ref

    def restore_ref(self, ref: WorldVersionRef | None) -> None:
        self._published_state = _state
        self._version_ref = ref

    def clear(self) -> None:
        global _state
        _state = None
        self._published_state = None
        self._version_ref = None


_world_head_cache = _WorldHeadCache()


def _get_state() -> GameState:
    return _world_head_cache.get()


async def _set_state(
    s: GameState,
    *,
    action_kind: str = "legacy_action",
    raw_text: str = "兼容行动",
) -> GameState:
    """Atomically settle an isolated legacy action state through the world graph.

    The compatibility patch cannot carry time or protected world identities.
    Elapsed time and registered boundary consumers are planned and applied by
    the same services used by ``/api/actions`` before one SQLite commit.
    """
    from api.action_service import (
        AIActionAdjudicator,
        ActionAdjudicationError,
        DefaultTimePlanner,
        DefaultWorldStateApplier,
    )
    from db import worlds
    from engine.elapsed_consumers import default_clock_registry
    from engine.activity import ActivityContractError, rebase_pending_checkpoints
    from engine.settlement import (
        COMPATIBILITY_PATCH_FIELDS,
        SettlementValidationError,
        validate_adjudication_proposal,
        validate_final_state,
    )
    from models.settlement import (
        ActionIntent,
        AdjudicationProposal,
        CompatibilityStatePatchDelta,
    )
    from models.world import (
        new_branch_id,
        new_client_action_id,
        new_delta_id,
        new_game_id,
        new_version_id,
    )

    ref = _get_world_head_ref()
    previous = (
        worlds.load_version(ref.version_id).state
        if ref is not None
        else _get_state().model_copy(deep=True)
    )
    if s.time != previous.time:
        raise ValueError(
            "legacy action attempted to write time directly; use the unified clock settlement",
        )
    action_id = new_client_action_id()
    intent = ActionIntent(
        game_id=ref.game_id if ref is not None else new_game_id(),
        branch_id=ref.branch_id if ref is not None else new_branch_id(),
        expected_parent_version_id=(
            ref.version_id if ref is not None else new_version_id()
        ),
        client_action_id=action_id,
        raw_text=raw_text.strip() or "兼容行动",
        action_kind=action_kind,
        mode=previous.phase,
    )
    adjudicated = await AIActionAdjudicator(_get_provider).adjudicate(
        intent,
        previous.model_copy(deep=True),
    )
    if adjudicated.duration_candidate is None:
        raise ActionAdjudicationError(
            "adjudication_duration_required",
            "AI 裁决未返回行动耗时，世界状态未提交",
        )

    # Legacy direct-state bootstrapping is itself durable. Delay it until the
    # strict provider/schema/duration gate succeeds so a failed first action
    # leaves no root/version behind.
    if ref is None:
        _, ref = _ensure_world_head()
        previous = worlds.load_version(ref.version_id).state
        if s.time != previous.time:
            raise ValueError(
                "legacy action attempted to write time directly; use the unified clock settlement",
            )
        intent = ActionIntent(
            game_id=ref.game_id,
            branch_id=ref.branch_id,
            expected_parent_version_id=ref.version_id,
            client_action_id=action_id,
            raw_text=raw_text.strip() or "兼容行动",
            action_kind=action_kind,
            mode=previous.phase,
        )

    before_values = previous.model_dump(mode="python")
    after_values = s.model_dump(mode="python")
    before_payload = previous.model_dump(mode="json")
    after_payload = s.model_dump(mode="json")
    changed_fields = [
        field
        for field in sorted(COMPATIBILITY_PATCH_FIELDS)
        if before_values[field] != after_values[field]
    ]
    deltas = []
    if changed_fields:
        deltas.append(
            CompatibilityStatePatchDelta(
                delta_id=new_delta_id(),
                adapter_name=action_kind,
                adapter_version="1",
                before_fields={field: before_payload[field] for field in changed_fields},
                after_fields={field: after_payload[field] for field in changed_fields},
                source_proposal=f"legacy-adapter:{action_kind}",
            ),
        )

    proposal = AdjudicationProposal(
        result_tier="success",
        key_factors=[
            *adjudicated.key_factors,
            "兼容玩法规则已在隔离世界副本中完成",
        ],
        immediate_changes=[f"兼容字段：{field}" for field in changed_fields],
        execution_status="completed",
        duration_candidate=adjudicated.duration_candidate,
        duration_reason=adjudicated.duration_reason,
        deltas=deltas,
        provider=adjudicated.provider,
    )
    validate_adjudication_proposal(intent, previous, proposal)

    registry = default_clock_registry()
    time_plan = DefaultTimePlanner(registry).plan_segment(intent, previous, proposal)
    changed, consumer_deltas, world_state_attribution = DefaultWorldStateApplier(
        registry,
    ).apply_with_facts(
        previous,
        proposal.deltas,
        time_plan,
    )
    validate_final_state(previous, changed)
    proposal_for_commit = proposal.model_copy(
        update={"deltas": [*proposal.deltas, *consumer_deltas]},
    )
    from models.world import new_settlement_id

    settlement_id = new_settlement_id()
    version_id = new_version_id()
    try:
        changed = rebase_pending_checkpoints(changed, version_id)
    except ActivityContractError as exc:
        raise SettlementValidationError(exc.code, exc.message) from exc
    result = worlds.commit_settlement(
        intent,
        changed,
        proposal_for_commit,
        time_plan=time_plan,
        world_state_attribution=world_state_attribution,
        settlement_id=settlement_id,
        version_id=version_id,
        actual_outcome=action_kind,
    )
    committed = worlds.load_version(result.version.version_id)
    _world_head_cache.publish(committed.state, committed.ref)
    return committed.state


def _get_world_head_ref() -> WorldVersionRef | None:
    return _world_head_cache.ref()


def _ensure_world_head() -> tuple[GameState, WorldVersionRef]:
    """Return the durable authority for the compatibility state slot.

    Legacy tests and older clients may still seed ``_state`` directly. Their
    first mutating unified action bootstraps exactly one immutable root and
    publishes the stored snapshot back into the discardable process cache.
    """
    state = _get_state()
    ref = _get_world_head_ref()
    if ref is not None:
        return state, ref

    from db import worlds

    root = worlds.create_game_with_root(
        state.model_copy(deep=True),
        source_kind="initial",
        source_ref="legacy-api-bootstrap",
    )
    snapshot = worlds.load_version(root.version_id)
    _world_head_cache.publish(snapshot.state, snapshot.ref)
    return snapshot.state, snapshot.ref


def _publish_world_head(state: GameState, ref: WorldVersionRef) -> None:
    state.world_metadata = state.world_metadata.model_copy(
        update={
            "game_id": ref.game_id,
            "branch_id": ref.branch_id,
            "version_id": ref.version_id,
            "source_kind": "settlement" if ref.settlement_id else state.world_metadata.source_kind,
            "source_ref": (
                str(ref.settlement_id)
                if ref.settlement_id
                else state.world_metadata.source_ref
            ),
        },
    )
    _world_head_cache.publish(state, ref)


def _reload_world_head(game_id: GameId, branch_id: BranchId) -> GameState:
    from db.worlds import load_branch_head

    snapshot = load_branch_head(game_id, branch_id)
    _world_head_cache.publish(snapshot.state, snapshot.ref)
    return snapshot.state


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
