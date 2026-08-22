from __future__ import annotations

from time import perf_counter

from fastapi.testclient import TestClient

from api import routes
from main import app
from models.game import DecreeResponse, GameState
from tests.benchmarks.manifests import percentile_ms


async def _safe_local_core(
    _request,
    *,
    stream_narrative_callback=None,
    narrative_path_id=None,
):
    del narrative_path_id
    state = GameState()
    if stream_narrative_callback is not None:
        await stream_narrative_callback("已校验的固定安全叙事。")
    response = DecreeResponse(
        state=state,
        narrative="已校验的固定安全叙事。",
        game_time=state.time,
        narrative_status="validated",
        narrative_path_id="decree_sse",
    ).model_dump()
    return response, [], None, state


def _one_stream_timing(client: TestClient) -> tuple[float, float]:
    started = perf_counter()
    queued_at: float | None = None
    validated_at: float | None = None
    narrative_at: float | None = None
    with client.stream(
        "POST",
        "/api/decree/stream",
        json={"decrees": []},
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line == "event: progress" and queued_at is None:
                queued_at = perf_counter()
            elif line == "event: narrative":
                narrative_at = perf_counter()
                break
            elif line.startswith("data: ") and '"stage": "validated"' in line:
                validated_at = perf_counter()
    assert queued_at is not None
    assert validated_at is not None
    assert narrative_at is not None
    return queued_at - started, narrative_at - validated_at


def test_local_sse_first_progress_and_safe_narrative_p95(monkeypatch):
    monkeypatch.setattr(routes, "_execute_decree_core", _safe_local_core)
    client = TestClient(app)
    _one_stream_timing(client)
    first_progress: list[float] = []
    validated_to_narrative: list[float] = []

    for _ in range(100):
        progress, narrative = _one_stream_timing(client)
        first_progress.append(progress)
        validated_to_narrative.append(narrative)

    assert percentile_ms(first_progress, 0.95) <= 250
    assert percentile_ms(validated_to_narrative, 0.95) <= 100
