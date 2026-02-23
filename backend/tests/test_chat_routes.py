import asyncio
import json

import pytest

from ai.provider import MockProvider, ResilientProvider
from api import chat_routes, routes
from api import state as api_state
from api.schemas import ChatRequest
from models.game import create_initial_state


@pytest.fixture(autouse=True)
def _restore_globals():
    old_state = api_state._state
    old_provider = api_state._provider
    try:
        yield
    finally:
        api_state._state = old_state
        api_state._provider = old_provider
        api_state.clear_chat_conversation()


def _mock_provider():
    return ResilientProvider(MockProvider(), timeout=1, retries=1)


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
    api_state._provider = _mock_provider()
    api_state._state = create_initial_state()
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
    api_state._provider = _mock_provider()
    api_state._state = create_initial_state()
    before = api_state._state.model_dump()

    stream_response = asyncio.run(
        chat_routes.chat_stream(
            ChatRequest(message=f"{chat_routes.EXPLORE_PREFIX}处理天启驾崩，信王继位")
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
    api_state._provider = _mock_provider()
    api_state._state = create_initial_state()
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
    api_state._provider = _mock_provider()
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
    assert api_state._state.national_treasury != before_treasury


def test_chat_execute_intent_emits_reactions_and_done_contains_reactions(monkeypatch):
    api_state._provider = _mock_provider()
    api_state._state = create_initial_state()
    _clear_blocking_script_events()

    expected_reactions = [
        {
            "minister_name": "钱谦益",
            "faction": "东林党",
            "reaction_type": "反对",
            "reaction_text": "此策恐伤民心。",
            "loyalty_change": -2,
        },
    ]

    async def _fake_execute_decree(_req):
        return {
            "narrative": "陛下，旨意已行。",
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
    api_state._provider = _mock_provider()
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
    api_state._provider = _mock_provider()
    api_state._state = create_initial_state()
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


def test_chat_conversation_buffer_trimmed_to_100_messages():
    api_state.clear_chat_conversation()
    for idx in range(105):
        api_state.append_chat_conversation("user", f"m{idx}")

    history = api_state.get_chat_conversation()
    assert len(history) == 100
    assert history[0]["content"] == "m5"
    assert history[-1]["content"] == "m104"


def test_new_game_clears_chat_conversation_buffer():
    api_state._provider = _mock_provider()
    api_state._state = create_initial_state()
    api_state.append_chat_conversation("user", "test")
    api_state.append_chat_conversation("assistant", "ok")
    assert len(api_state.get_chat_conversation()) == 2

    asyncio.run(routes.new_game())
    assert api_state.get_chat_conversation() == []
