import asyncio
import json

import pytest

from ai.base import GenerationResult
from ai.provider import ResilientProvider
from fakes import FakeProvider
from api import chat_routes, routes
from api import state as api_state
from api.schemas import ChatRequest
from db import narrative_memory, saves, worlds
from engine.core import inject_script_events
from models.enums import MinisterStatus
from models.game import GameTime, create_initial_state


@pytest.fixture(autouse=True)
def _restore_globals(monkeypatch, tmp_path):
    old_state = api_state._state
    old_provider = api_state._provider
    old_ref = api_state._get_world_head_ref()
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "chat-routes.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    try:
        yield
    finally:
        api_state._state = old_state
        api_state._provider = old_provider
        api_state._world_head_cache.restore_ref(old_ref)


def _fake_provider():
    return ResilientProvider(FakeProvider(), timeout=1, retries=1)


def _governance_opening_state():
    """治理开局态：拨到切换点 1356-03 + 注入脚本事件 + 激活已入仕大臣。

    （新档开局 1328-10 为跑团开局：无治理脚本事件、大臣均未入仕。）
    """
    state = create_initial_state()
    state.time = GameTime(year=1356, month=3, era_name="至正", era_year=16)
    inject_script_events(state)
    for m in state.ministers:
        if m.status == MinisterStatus.NOT_YET_ENTERED:
            m.status = MinisterStatus.ACTIVE if m.positions else MinisterStatus.IDLE
    return state


def _clear_blocking_script_events() -> None:
    assert api_state._state is not None
    api_state._state.active_events = [
        event
        for event in api_state._state.active_events
        if not (event.is_scripted and event.is_blocking)
    ]


async def _collect_stream_payload(stream_response) -> str:
    parts: list[str] = []
    async for chunk in stream_response.body_iterator:
        parts.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
    return "".join(parts)


def _parse_sse_events(payload: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for frame in payload.split("\n\n"):
        text = frame.strip()
        if not text:
            continue
        event_name = "message"
        data_lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        if not data_lines:
            continue
        data = json.loads("\n".join(data_lines))
        events.append((event_name, data))
    return events


def test_chat_query_intent_does_not_modify_state():
    api_state._provider = _fake_provider()
    api_state._state = create_initial_state()
    api_state._ensure_world_head()
    before = api_state._state.model_dump()

    stream_response = asyncio.run(chat_routes.chat_stream(ChatRequest(message="国库还有多少银两")))
    payload = asyncio.run(_collect_stream_payload(stream_response))
    events = _parse_sse_events(payload)

    names = [name for name, _ in events]
    assert "intent" in names
    assert "state" in names
    assert "done" in names

    intent_event = next(data for name, data in events if name == "intent")
    done_event = next(data for name, data in events if name == "done")
    assert intent_event["intent"] == "query"
    assert done_event["effects_applied"] is False
    assert done_event["minister_reactions"] == []
    assert done_event["triggered_events"] == []
    assert done_event["new_ministers"] == []
    assert done_event["game_over"] is None
    assert api_state._state.model_dump() == before


def test_chat_explore_prefix_forces_query_intent():
    api_state._provider = _fake_provider()
    api_state._state = create_initial_state()
    api_state._ensure_world_head()
    before = api_state._state.model_dump()

    stream_response = asyncio.run(
        chat_routes.chat_stream(
            ChatRequest(message=f"{chat_routes.EXPLORE_PREFIX}处理陈友谅东侵，应天守备")
        )
    )
    payload = asyncio.run(_collect_stream_payload(stream_response))
    events = _parse_sse_events(payload)

    names = [name for name, _ in events]
    assert "intent" in names
    assert "state" in names
    assert "done" in names

    intent_event = next(data for name, data in events if name == "intent")
    done_event = next(data for name, data in events if name == "done")
    assert intent_event["intent"] == "query"
    assert done_event["effects_applied"] is False
    assert api_state._state.model_dump() == before


def test_chat_execute_intent_blocked_by_pending_blocking_event():
    api_state._provider = _fake_provider()
    api_state._state = _governance_opening_state()
    api_state._ensure_world_head()
    before = api_state._state.model_dump()

    stream_response = asyncio.run(chat_routes.chat_stream(ChatRequest(message="加税")))
    payload = asyncio.run(_collect_stream_payload(stream_response))
    events = _parse_sse_events(payload)

    names = [name for name, _ in events]
    assert "intent" in names
    assert "error" in names
    assert "done" not in names

    error_event = next(data for name, data in events if name == "error")
    detail = error_event["detail"]
    assert error_event["status"] == 409
    assert detail["error_code"] == "blocking_event_pending"
    assert isinstance(detail.get("details"), dict)
    assert isinstance(detail["details"].get("event"), dict)
    assert api_state._state.model_dump() == before


def test_chat_execute_intent_applies_effects_and_updates_state():
    api_state._provider = _fake_provider()
    api_state._state = create_initial_state()
    _clear_blocking_script_events()
    before_treasury = api_state._state.national_treasury

    stream_response = asyncio.run(chat_routes.chat_stream(ChatRequest(message="加税")))
    payload = asyncio.run(_collect_stream_payload(stream_response))
    events = _parse_sse_events(payload)

    names = [name for name, _ in events]
    assert "intent" in names
    assert "effects" in names
    assert "done" in names

    intent_event = next(data for name, data in events if name == "intent")
    done_event = next(data for name, data in events if name == "done")
    assert intent_event["intent"] == "execute"
    assert done_event["effects_applied"] is True
    assert done_event["narrative_context_path_id"] == "ordinary_chat"
    assert done_event["narrative_path_id"] == "freeform_action"
    assert done_event["settlement_id"] is not None
    assert done_event["context_version_id"] is not None
    assert done_event["narrative_status"] in {
        "validated", "repaired", "sanitized", "fallback_facts",
    }
    assert api_state._state.national_treasury != before_treasury


def test_chat_execute_intent_emits_reactions_and_done_contains_reactions(monkeypatch):
    api_state._provider = _fake_provider()
    api_state._state = create_initial_state()
    _clear_blocking_script_events()

    expected_reactions = [
        {
            "minister_name": "宋濂",
            "faction": "幕府文臣",
            "reaction_type": "反对",
            "reaction_text": "此策恐伤民心。",
            "loyalty_change": -2,
        },
    ]

    async def _fake_execute_decree(_req):
        return {
            "narrative": "主公，旨意已行。",
            "delta": {"national_treasury": 30, "civil_morale": -10},
            "minister_reactions": expected_reactions,
        }

    monkeypatch.setattr(chat_routes, "execute_decree", _fake_execute_decree)

    stream_response = asyncio.run(chat_routes.chat_stream(ChatRequest(message="加税")))
    payload = asyncio.run(_collect_stream_payload(stream_response))
    events = _parse_sse_events(payload)

    names = [name for name, _ in events]
    assert "intent" in names
    assert "effects" in names
    assert "reactions" in names
    assert "done" in names

    reactions_event = next(data for name, data in events if name == "reactions")
    done_event = next(data for name, data in events if name == "done")
    assert reactions_event["minister_reactions"] == expected_reactions
    assert done_event["minister_reactions"] == expected_reactions
    assert done_event["triggered_events"] == []
    assert done_event["new_ministers"] == []
    assert done_event["game_over"] is None


def test_chat_advance_month_intent_advances_game_time():
    api_state._provider = _fake_provider()
    api_state._state = create_initial_state()
    _clear_blocking_script_events()
    before = (api_state._state.time.year, api_state._state.time.month)

    stream_response = asyncio.run(chat_routes.chat_stream(ChatRequest(message="进入下月")))
    payload = asyncio.run(_collect_stream_payload(stream_response))
    events = _parse_sse_events(payload)

    names = [name for name, _ in events]
    assert "intent" in names
    assert "done" in names

    intent_event = next(data for name, data in events if name == "intent")
    done_event = next(data for name, data in events if name == "done")
    assert intent_event["intent"] == "advance_month"
    assert done_event["narrative_context_path_id"] == "ordinary_chat"
    assert done_event["narrative_path_id"] == "monthly_review"
    assert done_event["settlement_id"] is not None
    assert done_event["context_version_id"] is not None
    assert done_event["narrative_status"] in {
        "validated", "repaired", "sanitized", "fallback_facts",
    }
    assert isinstance(done_event["triggered_events"], list)
    assert isinstance(done_event["new_ministers"], list)
    assert done_event["minister_reactions"] == []
    assert (
        done_event["game_over"] is None
        or (
            isinstance(done_event["game_over"], dict)
            and "result" in done_event["game_over"]
            and "message" in done_event["game_over"]
        )
    )
    after = (api_state._state.time.year, api_state._state.time.month)
    assert after != before


def test_chat_advance_month_blocked_by_pending_blocking_event():
    api_state._provider = _fake_provider()
    api_state._state = _governance_opening_state()
    api_state._ensure_world_head()
    before = api_state._state.model_dump()

    stream_response = asyncio.run(chat_routes.chat_stream(ChatRequest(message="进入下月")))
    payload = asyncio.run(_collect_stream_payload(stream_response))
    events = _parse_sse_events(payload)

    names = [name for name, _ in events]
    assert "intent" in names
    assert "error" in names
    assert "done" not in names

    error_event = next(data for name, data in events if name == "error")
    detail = error_event["detail"]
    assert error_event["status"] == 409
    assert detail["error_code"] == "blocking_event_pending"
    assert isinstance(detail.get("details"), dict)
    assert isinstance(detail["details"].get("event"), dict)
    assert api_state._state.model_dump() == before


def test_chat_query_uses_strict_pipeline_and_durable_scoped_memory():
    class _CapturedProvider(FakeProvider):
        def __init__(self):
            self.histories: list[list[dict[str, str]]] = []
            self.legacy_query_calls = 0

        async def classify_chat_intent(self, message, state, history):
            self.histories.append([dict(item) for item in history])
            return await super().classify_chat_intent(message, state, history)

        async def generate_text_once(self, prompt, **kwargs):
            if "ACTION_INTENT=" in prompt:
                return await super().generate_text_once(prompt, **kwargs)
            return GenerationResult(text="国库数额以当前已提交世界状态为准。")

        async def chat_query(self, *args, **kwargs):
            self.legacy_query_calls += 1
            return "RAW_LEGACY_QUERY"

    inner = _CapturedProvider()
    api_state._provider = ResilientProvider(inner, timeout=1, retries=1)
    api_state._state = create_initial_state()

    response = asyncio.run(chat_routes.chat_stream(ChatRequest(message="国库还有多少银两")))
    payload = asyncio.run(_collect_stream_payload(response))
    events = _parse_sse_events(payload)
    names = [name for name, _ in events]
    first_chunk = names.index("narrative_chunk")
    done = next(data for name, data in events if name == "done")

    assert inner.histories == [[]]
    assert inner.legacy_query_calls == 0
    assert "RAW_LEGACY_QUERY" not in payload
    assert any(
        name == "progress" and data["stage"] == "validated"
        for name, data in events[:first_chunk]
    )
    assert done["narrative_status"] == "validated"
    assert done["narrative_context_path_id"] == "ordinary_chat"
    assert done["narrative_path_id"] == "chat_sse"
    assert done["context_version_id"] is not None
    assert done["narrative_request_id"]
    assert done["narrative_progress"] == [
        "context_ready", "generating", "validating", "validated",
    ]

    ref = api_state._get_world_head_ref()
    memories = narrative_memory.list_visible_memories(
        game_id=ref.game_id,
        branch_id=ref.branch_id,
        version_id=ref.version_id,
        mode="chat",
        topic_id="chat",
        current_phase=api_state._state.phase,
        current_chapter=api_state._state.chapter,
    )
    assert [(item.role, item.content) for item in memories] == [
        ("user", "国库还有多少银两"),
        ("assistant", "国库数额以当前已提交世界状态为准。"),
    ]


def test_chat_sse_hides_classifier_and_invalid_provider_text_until_repair():
    class _AdversarialProvider(FakeProvider):
        async def classify_chat_intent(self, message, state, history):
            del message, state, history
            return {
                "intent": "query",
                "confidence": 1.0,
                "reason": "RAW_CLASSIFIER_REASON_CANARY",
            }

        async def generate_text_once(self, prompt, **kwargs):
            del kwargs
            if "REPAIR_REQUIREMENTS=" in prompt:
                return GenerationResult(text="当前世界仍按已提交事实继续，可再选择下一步行动。")
            return GenerationResult(
                text="RAW_CHAT_CANDIDATE_CANARY：主角身死，此局已终。",
            )

    api_state._provider = ResilientProvider(
        _AdversarialProvider(), timeout=1, retries=1,
    )
    api_state._state = create_initial_state()

    response = asyncio.run(chat_routes.chat_stream(ChatRequest(message="当前局势如何")))
    payload = asyncio.run(_collect_stream_payload(response))
    events = _parse_sse_events(payload)
    names = [name for name, _ in events]
    first_chunk = names.index("narrative_chunk")
    visible_progress = [
        data["stage"] for name, data in events[:first_chunk] if name == "progress"
    ]
    intent = next(data for name, data in events if name == "intent")
    done = next(data for name, data in events if name == "done")

    assert intent["reason"] == "识别为局势查询"
    assert visible_progress == [
        "context_ready", "generating", "validating", "validated",
    ]
    assert done["narrative_status"] == "repaired"
    assert done["narrative_context_path_id"] == "ordinary_chat"
    assert done["narrative_path_id"] == "chat_sse"
    assert done["context_version_id"] is not None
    assert done["narrative_request_id"]
    assert "repairing" in done["narrative_progress"]
    assert "RAW_CLASSIFIER_REASON_CANARY" not in payload
    assert "RAW_CHAT_CANDIDATE_CANARY" not in payload
    assert "身死" not in payload
    assert "此局已终" not in payload


def test_chat_memory_does_not_cross_into_a_different_game():
    class _CapturedProvider(FakeProvider):
        def __init__(self):
            self.histories: list[list[dict[str, str]]] = []

        async def classify_chat_intent(self, message, state, history):
            self.histories.append([dict(item) for item in history])
            return {"intent": "query", "confidence": 1.0, "reason": "test"}

        async def generate_text_once(self, prompt, **kwargs):
            del prompt, kwargs
            return GenerationResult(text="仅依据当前世界作答。")

    inner = _CapturedProvider()
    api_state._provider = ResilientProvider(inner, timeout=1, retries=1)
    api_state._state = create_initial_state()
    first = asyncio.run(chat_routes.chat_stream(ChatRequest(message="第一局的秘密")))
    asyncio.run(_collect_stream_payload(first))

    second_root = worlds.create_game_with_root(create_initial_state())
    second_snapshot = worlds.load_version(second_root.version_id)
    api_state._publish_world_head(second_snapshot.state, second_snapshot.ref)
    second = asyncio.run(chat_routes.chat_stream(ChatRequest(message="第二局现在如何")))
    asyncio.run(_collect_stream_payload(second))

    assert inner.histories == [[], []]
