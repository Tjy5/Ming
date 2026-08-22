import asyncio
import json
from uuid import UUID

import pytest
from fastapi import HTTPException

from ai.base import GenerationResult
from ai.narrative_validators import facts_narrative
from ai.provider import ResilientProvider
from api import narrative_routes, routes
from api import state as api_state
from api.schemas import (
    DecreeStreamErrorPayload,
    DecreeStreamFinalPayload,
    DecreeStreamMemorialPayload,
    DecreeStreamNarrativePayload,
    DecreeStreamProgressPayload,
)
from db import narrative_memory, saves, worlds
from models.enums import DecreeType, MinisterStatus
from models.game import DecreeResponse, StructuredDecree, create_initial_state
from fakes import FakeProvider


class _StrictNarrativeProvider(FakeProvider):
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.narrative_calls = 0
        self.legacy_stream_calls = 0

    async def generate_text_once(self, prompt, **kwargs):
        if "ACTION_INTENT=" in prompt:
            return await super().generate_text_once(prompt, **kwargs)
        self.narrative_calls += 1
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return GenerationResult(text=output)

    async def stream_narrative(self, *args, **kwargs):
        del args, kwargs
        self.legacy_stream_calls += 1
        yield "RAW_PROVIDER_CHUNK"


class _FailingAdjudicationProvider(FakeProvider):
    async def generate_text_once(self, prompt, **kwargs):
        del prompt, kwargs
        raise RuntimeError("private provider failure body")


class _BlockingProvider(FakeProvider):
    def __init__(self, *, block_adjudication: bool):
        self.block_adjudication = block_adjudication
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def generate_text_once(self, prompt, **kwargs):
        is_adjudication = "ACTION_INTENT=" in prompt
        if is_adjudication != self.block_adjudication:
            return await super().generate_text_once(prompt, **kwargs)
        self.started.set()
        try:
            await asyncio.Future()
        finally:
            self.cancelled.set()


class _RetryFailingNarrativeProvider(FakeProvider):
    def __init__(self):
        self.narrative_calls = 0

    async def generate_text_once(self, prompt, **kwargs):
        if "ACTION_INTENT=" in prompt:
            return await super().generate_text_once(prompt, **kwargs)
        self.narrative_calls += 1
        raise RuntimeError("private provider retry body")


@pytest.fixture
def _isolated_runtime(monkeypatch, tmp_path):
    old_state = api_state._state
    old_provider = api_state._provider
    old_ref = api_state._get_world_head_ref()
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "strict-narrative-stream.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    api_state._state = create_initial_state()
    try:
        yield
    finally:
        api_state._state = old_state
        api_state._provider = old_provider
        api_state._world_head_cache.restore_ref(old_ref)


async def _collect_stream(response) -> str:
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
    return "".join(chunks)


def _events(payload: str) -> list[tuple[str, dict]]:
    result: list[tuple[str, dict]] = []
    for block in payload.strip().split("\n\n"):
        if not block:
            continue
        lines = block.splitlines()
        event = next(line[7:] for line in lines if line.startswith("event: "))
        data = next(line[6:] for line in lines if line.startswith("data: "))
        result.append((event, json.loads(data)))
    return result


def _structured_request() -> routes.DecreeRequest:
    return routes.DecreeRequest(
        decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)],
    )


def _row_count(table: str) -> int:
    assert table in {"versions", "settlements", "narrative_artifacts"}
    with saves._connect() as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_invalid_provider_candidate_and_raw_stream_chunks_are_never_visible(
    _isolated_runtime,
):
    provider = _StrictNarrativeProvider([
        "徐达：臣仍在主持军务。",
        "朝廷已按当前状态执行政令。",
    ])
    api_state._provider = ResilientProvider(provider, timeout=1, retries=1)
    minister = next(item for item in api_state._state.ministers if item.name == "徐达")
    minister.status = MinisterStatus.REMOVED

    response = asyncio.run(routes.execute_decree_stream(_structured_request()))
    payload = asyncio.run(_collect_stream(response))

    assert "臣仍在主持军务" not in payload
    assert "RAW_PROVIDER_CHUNK" not in payload
    assert "朝廷已按当前状态执行政令。" in payload
    assert provider.narrative_calls == 2
    assert provider.legacy_stream_calls == 0


def test_precommit_adjudication_failure_writes_no_world_or_narrative_rows(
    _isolated_runtime,
):
    api_state._provider = ResilientProvider(
        _FailingAdjudicationProvider(),
        timeout=1,
        retries=1,
    )

    response = asyncio.run(routes.execute_decree_stream(_structured_request()))
    payload = asyncio.run(_collect_stream(response))
    events = _events(payload)

    assert [event for event, _ in events] == ["progress", "error"]
    assert events[-1][1]["detail"]["error_code"] == "adjudication_provider_error"
    assert "private provider failure body" not in payload
    assert api_state._get_world_head_ref() is None
    assert _row_count("versions") == 0
    assert _row_count("settlements") == 0
    assert _row_count("narrative_artifacts") == 0


def test_first_narrative_chunk_follows_validation_complete_stage(
    _isolated_runtime,
):
    provider = _StrictNarrativeProvider(["政令已按已提交事实执行。"])
    api_state._provider = ResilientProvider(provider, timeout=1, retries=1)

    response = asyncio.run(routes.execute_decree_stream(_structured_request()))
    events = _events(asyncio.run(_collect_stream(response)))
    names = [event for event, _ in events]
    first_narrative = names.index("narrative")

    assert any(
        event == "progress" and data["stage"] == "validated"
        for event, data in events[:first_narrative]
    )
    assert all(event != "narrative" for event, _ in events[:first_narrative])
    assert names.count("final") == 1
    assert names[-1] == "final"


def test_normal_stream_payloads_validate_against_shared_schemas(_isolated_runtime):
    provider = _StrictNarrativeProvider(["政令已按已提交事实执行。"])
    api_state._provider = ResilientProvider(provider, timeout=1, retries=1)

    response = asyncio.run(routes.execute_decree_stream(_structured_request()))
    events = _events(asyncio.run(_collect_stream(response)))
    schemas = {
        "progress": DecreeStreamProgressPayload,
        "narrative": DecreeStreamNarrativePayload,
        "memorial": DecreeStreamMemorialPayload,
        "final": DecreeStreamFinalPayload,
        "error": DecreeStreamErrorPayload,
    }

    for event, payload in events:
        schemas[event].model_validate(payload)


@pytest.mark.parametrize("status, expected_status", [(418, 418), (799, 500)])
def test_malformed_http_error_is_sanitized(
    _isolated_runtime,
    monkeypatch,
    status,
    expected_status,
):
    async def fail_core(*_args, **_kwargs):
        raise HTTPException(status, detail={"private": "provider-secret"})

    monkeypatch.setattr(routes, "_execute_decree_core", fail_core)
    response = asyncio.run(routes.execute_decree_stream(_structured_request()))
    payload = asyncio.run(_collect_stream(response))
    events = _events(payload)

    assert [name for name, _ in events] == ["progress", "error"]
    error = DecreeStreamErrorPayload.model_validate(events[-1][1])
    assert error.status == expected_status
    assert error.detail.error_code == "stream_http_error"
    assert error.detail.details is None
    assert "provider-secret" not in payload


def test_resilient_retries_then_uses_configured_rule_fallback(_isolated_runtime):
    inner = _RetryFailingNarrativeProvider()
    fallback_calls: list[str] = []

    def configured_fallback(context):
        fallback_calls.append(str(context.settlement_id))
        return facts_narrative(context)

    api_state._provider = ResilientProvider(
        inner,
        timeout=1,
        retries=2,
        narrative_rule_fallback=configured_fallback,
    )

    response = asyncio.run(routes.execute_decree_stream(_structured_request()))
    payload = asyncio.run(_collect_stream(response))
    events = _events(payload)
    final = DecreeStreamFinalPayload.model_validate(events[-1][1]).response

    assert inner.narrative_calls == 2
    assert len(fallback_calls) == 1
    assert final.narrative_status == "fallback_facts"
    assert "private provider retry body" not in payload


def test_client_disconnect_before_commit_cancels_without_writes(_isolated_runtime):
    async def scenario():
        inner = _BlockingProvider(block_adjudication=True)
        api_state._provider = ResilientProvider(inner, timeout=10, retries=1)
        response = await routes.execute_decree_stream(_structured_request())
        iterator = response.body_iterator
        first = await anext(iterator)
        assert "event: progress" in str(first)
        pending = asyncio.create_task(anext(iterator))
        await asyncio.wait_for(inner.started.wait(), timeout=1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.wait_for(inner.cancelled.wait(), timeout=1)

    asyncio.run(scenario())

    assert api_state._get_world_head_ref() is None
    assert _row_count("versions") == 0
    assert _row_count("settlements") == 0
    assert _row_count("narrative_artifacts") == 0


def test_client_disconnect_after_commit_preserves_world_state(_isolated_runtime):
    async def scenario():
        inner = _BlockingProvider(block_adjudication=False)
        api_state._provider = ResilientProvider(inner, timeout=10, retries=1)
        response = await routes.execute_decree_stream(_structured_request())
        iterator = response.body_iterator
        await anext(iterator)
        pending = asyncio.create_task(anext(iterator))
        await asyncio.wait_for(inner.started.wait(), timeout=2)
        assert _row_count("settlements") == 1
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.wait_for(inner.cancelled.wait(), timeout=1)

    asyncio.run(scenario())

    ref = api_state._get_world_head_ref()
    assert ref is not None
    assert worlds.load_version(ref.version_id).ref == ref
    assert _row_count("settlements") == 1
    assert _row_count("narrative_artifacts") == 0


def test_non_streaming_response_remains_decree_response(_isolated_runtime):
    provider = _StrictNarrativeProvider(["政令已按已提交事实执行。"])
    api_state._provider = ResilientProvider(provider, timeout=1, retries=1)

    payload = asyncio.run(routes.execute_decree(_structured_request()))

    response = DecreeResponse.model_validate(payload)
    assert response.settlement_id is not None
    assert response.narrative_status == "validated"


def test_postcommit_narrative_failure_returns_facts_with_settlement_id(
    _isolated_runtime,
):
    provider = _StrictNarrativeProvider([RuntimeError("secret raw response")])
    api_state._provider = ResilientProvider(provider, timeout=1, retries=1)

    response = asyncio.run(routes.execute_decree_stream(_structured_request()))
    payload = asyncio.run(_collect_stream(response))
    events = _events(payload)
    final = next(data["response"] for event, data in events if event == "final")

    assert "secret raw response" not in payload
    assert final["narrative_status"] == "fallback_facts"
    assert final["narrative_path_id"] == "decree_sse"
    assert final["context_version_id"] is not None
    assert final["narrative_artifact_id"] is not None
    assert final["narrative_request_id"]
    assert UUID(final["settlement_id"])
    assert final["settlement_id"] in final["narrative"]
    assert _row_count("settlements") == 1
    assert _row_count("narrative_artifacts") == 1


def test_sse_progress_uses_server_owned_strict_pipeline_stages(
    _isolated_runtime,
):
    provider = _StrictNarrativeProvider(["政令已按已提交事实执行。"])
    api_state._provider = ResilientProvider(provider, timeout=1, retries=1)

    response = asyncio.run(routes.execute_decree_stream(_structured_request()))
    events = _events(asyncio.run(_collect_stream(response)))
    final = next(data["response"] for event, data in events if event == "final")

    assert final["narrative_path_id"] == "decree_sse"
    assert final["context_version_id"] is not None
    assert final["narrative_artifact_id"] is not None
    assert final["narrative_request_id"]
    assert final["narrative_progress"] == [
        "context_ready", "generating", "validating", "validated",
    ]
    assert any(
        event == "progress" and data["stage"] == "validated"
        for event, data in events
    )


def test_replay_reuses_only_the_matching_path_artifact_without_resettlement(
    _isolated_runtime,
):
    provider = _StrictNarrativeProvider([
        "结构化政令已执行。",
        "自由行动叙事独立生成。",
    ])
    api_state._provider = ResilientProvider(provider, timeout=1, retries=1)

    first = asyncio.run(routes.execute_decree(_structured_request()))
    settlement_id = first["settlement_id"]
    facts = worlds.get_settlement(settlement_id)
    state = worlds.load_version(facts.result_version_id).state
    settlement_count = _row_count("settlements")

    freeform = asyncio.run(narrative_routes.generate_committed_narrative(
        state=state,
        facts=facts,
        path_id="freeform_action",
        topic_id="decree",
        action_text="harsh_punishment",
    ))
    replayed = asyncio.run(narrative_routes.generate_committed_narrative(
        state=state,
        facts=facts,
        path_id="structured_action",
        topic_id="decree",
        action_text="harsh_punishment",
        reuse_current=True,
    ))

    structured_current = narrative_memory.get_current_artifact(
        facts.game_id, facts.branch_id, facts.settlement_id, "structured_action",
    )
    freeform_current = narrative_memory.get_current_artifact(
        facts.game_id, facts.branch_id, facts.settlement_id, "freeform_action",
    )
    assert _row_count("settlements") == settlement_count == 1
    assert structured_current is not None and freeform_current is not None
    assert replayed.artifact_id == structured_current.artifact_id == first["narrative_artifact_id"]
    assert freeform.artifact_id == freeform_current.artifact_id
    assert freeform.artifact_id != replayed.artifact_id
    assert provider.narrative_calls == 2
