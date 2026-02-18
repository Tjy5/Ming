import asyncio
import os

import pytest
from fastapi import HTTPException

from ai.provider import MockProvider, ResilientProvider
from api import routes
from models.enums import DecreeType, PersonnelAction
from models.game import (
    CourtAssembly,
    FreeformResult,
    HistoryEntry,
    PolicySuggestion,
    StructuredDecree,
    create_initial_state,
)


@pytest.fixture(autouse=True)
def _restore_route_globals():
    old_state = routes._state
    old_provider = routes._provider
    try:
        yield
    finally:
        routes._state = old_state
        routes._provider = old_provider


def _mock_provider():
    return ResilientProvider(MockProvider(), timeout=1, retries=1)


def test_execute_decree_is_atomic_when_later_decree_fails_precondition():
    routes._provider = _mock_provider()
    routes._state = create_initial_state()
    routes._state.treasury = 25
    before = routes._state.model_dump()

    req = routes.DecreeRequest(
        decrees=[
            StructuredDecree(type=DecreeType.RECRUIT_TROOPS),
            StructuredDecree(type=DecreeType.TAX_DECREASE),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(req))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "precondition_failed"
    assert routes._state is not None
    assert routes._state.model_dump() == before


def test_personnel_target_must_exist():
    routes._provider = _mock_provider()
    routes._state = create_initial_state()
    before = routes._state.model_dump()

    req = routes.DecreeRequest(
        decrees=[
            StructuredDecree(
                type=DecreeType.PERSONNEL,
                target="不存在的人",
                sub_action=PersonnelAction.APPOINT,
            ),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(req))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "invalid_decree"
    assert "目标人物不存在" in exc_info.value.detail["message"]
    assert routes._state is not None
    assert routes._state.model_dump() == before


def test_get_history_normalizes_negative_offset_and_small_limit():
    routes._state = create_initial_state()
    routes._state.history_log = [
        HistoryEntry(year=1627, month=i, decree_type="x")
        for i in range(1, 6)
    ]

    result = asyncio.run(routes.get_history(offset=-2, limit=0))
    assert result["offset"] == 0
    assert result["limit"] == 1
    assert len(result["entries"]) == 1
    assert result["entries"][0]["month"] == 1


def test_execute_decree_summary_includes_action_implications_for_commentary():
    routes._provider = _mock_provider()
    routes._state = create_initial_state()

    req = routes.DecreeRequest(
        decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)]
    )
    result = asyncio.run(routes.execute_decree(req))

    summary = result["turn_summary"]
    assert summary is not None
    assert summary["action_implications"]
    assert any("严刑峻法" in item for item in summary["action_implications"])
    if not summary["major_events"]:
        assert "朝政有变" in summary["commentary"]


def test_execute_decree_wait_turn_includes_memorial_triggers():
    routes._provider = _mock_provider()
    state = create_initial_state()
    state.factions[0].satisfaction = 10
    routes._state = state

    # Use a valid active script_id for the wait-turn path (no free_text, no decrees)
    active_script = next(
        (e.script_id for e in state.active_events if e.script_id), None
    )
    result = asyncio.run(routes.execute_decree(
        routes.DecreeRequest(source_script_id=active_script)
    ))

    assert "memorial_triggers" in result
    assert len(result["memorial_triggers"]) >= 1


def test_adopt_suggestion_includes_memorial_triggers():
    routes._provider = _mock_provider()
    state = create_initial_state()
    state.factions[0].satisfaction = 10
    state.last_assembly = CourtAssembly(
        topic="严刑峻法之议",
        decree_type=DecreeType.HARSH_PUNISHMENT,
        suggestions=[
            PolicySuggestion(
                title="严刑整肃",
                description="以重典整饬朝纲",
                related_decree=StructuredDecree(type=DecreeType.HARSH_PUNISHMENT),
            )
        ],
    )
    routes._state = state

    result = asyncio.run(routes.adopt_suggestion(routes.AdoptSuggestionRequest(suggestion_index=0)))

    assert "memorial_triggers" in result
    assert len(result["memorial_triggers"]) >= 1


def test_split_stream_sentences_preserves_sentence_boundaries():
    text = "朕已知晓。即刻施行！\n再议后续；"
    result = routes._split_stream_sentences(text)
    assert result == ["朕已知晓。", "即刻施行！", "再议后续；"]


def test_execute_decree_stream_emits_final_event():
    routes._provider = _mock_provider()
    routes._state = create_initial_state()

    req = routes.DecreeRequest(decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)])
    stream_response = asyncio.run(routes.execute_decree_stream(req))

    async def _collect_stream():
        parts: list[str] = []
        async for chunk in stream_response.body_iterator:
            parts.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
        return "".join(parts)

    payload = asyncio.run(_collect_stream())
    assert "event: final" in payload
    assert "event: narrative" in payload


def test_execute_decree_stream_emits_provider_token_chunks():
    class _TokenStreamMockProvider(MockProvider):
        async def generate_narrative(self, *a, **kw) -> str:
            return "甲乙"

        async def stream_narrative(self, *a, **kw):
            yield "甲"
            yield "乙"

    routes._provider = ResilientProvider(_TokenStreamMockProvider(), timeout=1, retries=1)
    routes._state = create_initial_state()

    req = routes.DecreeRequest(decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)])
    stream_response = asyncio.run(routes.execute_decree_stream(req))

    async def _collect_stream():
        parts: list[str] = []
        async for chunk in stream_response.body_iterator:
            parts.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
        return "".join(parts)

    payload = asyncio.run(_collect_stream())
    assert payload.count("event: narrative") >= 2
    assert "\"chunk\": \"甲\"" in payload
    assert "\"chunk\": \"乙\"" in payload


def test_execute_decree_stream_emits_fallback_narrative_chunk():
    class _EmptyStreamMockProvider(MockProvider):
        async def generate_narrative(self, *a, **kw) -> str:
            return "整段叙事"

        async def stream_narrative(self, *a, **kw):
            if False:
                yield ""

    routes._provider = ResilientProvider(_EmptyStreamMockProvider(), timeout=1, retries=1)
    routes._state = create_initial_state()

    req = routes.DecreeRequest(decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)])
    stream_response = asyncio.run(routes.execute_decree_stream(req))

    async def _collect_stream():
        parts: list[str] = []
        async for chunk in stream_response.body_iterator:
            parts.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
        return "".join(parts)

    payload = asyncio.run(_collect_stream())
    assert "event: narrative" in payload
    assert "\"chunk\": \"整段叙事\"" in payload


def test_update_ai_settings_persists_provider_and_returns_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "_ENV_FILE_PATH", tmp_path / ".env")
    monkeypatch.setenv("AI_PROVIDER", "mock")
    routes._provider = object()

    result = asyncio.run(routes.update_ai_settings(routes.AISettingsRequest(provider="mock")))

    assert result["provider"] == "mock"
    assert os.getenv("AI_PROVIDER") == "mock"
    assert routes._provider is not None
    assert (tmp_path / ".env").exists()
    assert "AI_PROVIDER=mock" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_list_ai_models_openai_compatible(monkeypatch):
    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "model-b"}, {"id": "model-a"}]}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr(routes.httpx, "AsyncClient", lambda **kwargs: _FakeClient())
    req = routes.AIModelListRequest(
        provider="openai",
        api_key="sk-test",
        base_url="https://example.com/v1",
    )

    result = asyncio.run(routes.list_ai_models(req))

    assert result["provider"] == "openai"
    assert result["source"] == "openai-compatible"
    assert result["models"] == ["model-a", "model-b"]


def test_get_ai_settings_masks_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL_NAME", "main-model")

    result = asyncio.run(routes.get_ai_settings("openai"))

    assert result["provider"] == "openai"
    assert result["api_key"] == "********"


def test_list_ai_models_resolves_masked_api_key(monkeypatch):
    captured_headers: dict[str, str] = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "model-a"}]}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            nonlocal captured_headers
            captured_headers = kwargs.get("headers", {})
            return _FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
    monkeypatch.setattr(routes.httpx, "AsyncClient", lambda **kwargs: _FakeClient())
    req = routes.AIModelListRequest(
        provider="openai",
        api_key="********",
        base_url="https://example.com/v1",
    )

    result = asyncio.run(routes.list_ai_models(req))

    assert result["models"] == ["model-a"]
    assert captured_headers.get("Authorization") == "Bearer sk-real"


def test_list_ai_models_rejects_private_base_url_by_default():
    req = routes.AIModelListRequest(
        provider="openai",
        api_key="sk-test",
        base_url="http://127.0.0.1:8000/v1",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.list_ai_models(req))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "invalid_base_url"


# ── 10.3 FREEFORM_EMPTY error when source_script_id present ──

def test_freeform_empty_returns_error_with_script_id():
    class _EmptyFreeformMock(MockProvider):
        async def process_freeform(self, text, game_state, *, script_context=None):
            return FreeformResult(
                effects={}, narrative="", rationale="",
                reactions=[], new_events=[],
            )

    routes._provider = ResilientProvider(_EmptyFreeformMock(), timeout=1, retries=1)
    state = create_initial_state()
    routes._state = state

    active_script = next(
        (e.script_id for e in state.active_events if e.script_id), None
    )
    assert active_script is not None

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(
            routes.DecreeRequest(
                source_script_id=active_script,
                free_text="无意义的话",
            )
        ))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "FREEFORM_EMPTY"


# ── 10.10 200-char limit boundary test ──

def test_200_char_limit_accepted():
    routes._provider = _mock_provider()
    routes._state = create_initial_state()

    text_200 = "字" * 200
    # Should not raise INPUT_TOO_LONG (may raise other errors like FREEFORM_EMPTY)
    try:
        asyncio.run(routes.execute_decree(
            routes.DecreeRequest(free_text=text_200)
        ))
    except HTTPException as e:
        assert e.detail.get("error_code") != "INPUT_TOO_LONG"


def test_201_char_limit_rejected():
    routes._provider = _mock_provider()
    routes._state = create_initial_state()

    text_201 = "字" * 201
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(
            routes.DecreeRequest(free_text=text_201)
        ))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error_code"] == "INPUT_TOO_LONG"


# ── 10.11 source_script_id validation tests ──

def test_invalid_script_id_rejected():
    routes._provider = _mock_provider()
    routes._state = create_initial_state()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(
            routes.DecreeRequest(source_script_id="nonexistent-script")
        ))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "INVALID_SCRIPT_ID"


def test_script_already_resolved_rejected():
    routes._provider = _mock_provider()
    state = create_initial_state()
    active_script = next(
        (e.script_id for e in state.active_events if e.script_id), None
    )
    assert active_script is not None
    state.resolved_script_ids.add(active_script)
    routes._state = state

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(
            routes.DecreeRequest(source_script_id=active_script, free_text="test")
        ))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "SCRIPT_ALREADY_RESOLVED"


def test_script_not_active_rejected():
    routes._provider = _mock_provider()
    state = create_initial_state()
    # Use a valid script ID from registry that's NOT in active_events
    from engine.scripts import SCRIPT_REGISTRY
    non_active_id = next(
        sid for sid in SCRIPT_REGISTRY
        if sid not in {e.script_id for e in state.active_events}
    )
    routes._state = state

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(
            routes.DecreeRequest(source_script_id=non_active_id, free_text="test")
        ))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "SCRIPT_NOT_ACTIVE"
