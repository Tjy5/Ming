from __future__ import annotations

import json
import os
import platform
import sqlite3
import statistics
from contextlib import closing
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from fastapi.testclient import TestClient

from ai.narrative_context import (
    build_narrative_context,
    estimate_prompt_tokens,
    project_narrative_context_for_prompt,
)
from api import routes
from api.history_service import (
    HISTORY_QUERY_CACHE_MAX_ENTRIES,
    clear_history_query_cache,
    filter_history_entries,
    filter_history_entries_cached,
)
from db import maintenance, saves, worlds
from main import app
from models.game import DecreeResponse, GameState, create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal
from models.world import RegionEntity, new_client_action_id
from tests.benchmarks.manifests import (
    build_history_entries,
    canonical_sha256,
    history_dataset_sha256,
    history_result_sha256,
    load_manifest,
    percentile_ms,
)
from tests.benchmarks.storage_fixture import generate_storage_fixture


SSE_FIRST_PROGRESS_P95_MAX_MS = 250.0
SSE_VALIDATED_TO_NARRATIVE_P95_MAX_MS = 100.0
PROMPT_PROJECTION_P95_MAX_MS = 100.0


def _prompt_context(db_path: Path):
    saves.DB_PATH = db_path
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    state = worlds.load_version(root.version_id).state
    target_region_id = next(
        entity_id
        for entity_id, entity in state.entity_registry.items()
        if isinstance(entity, RegionEntity) and entity.legacy_name == "应天"
    )
    target_entity_id = next(
        entity_id
        for entity_id, entity in state.entity_registry.items()
        if not isinstance(entity, RegionEntity)
    )
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="核查应天灾情",
        action_kind="decree",
        target_region_id=target_region_id,
        regional_targets=["应天"],
        target_entity_ids=[target_entity_id],
    )
    proposal = AdjudicationProposal(
        result_tier="success",
        key_factors=["固定语料事实"],
        immediate_changes=["只记录已提交结算"],
        execution_status="completed",
    )
    result = worlds.commit_settlement(intent, state, proposal)
    committed = worlds.load_version(result.version.version_id).state
    return build_narrative_context(
        path_id="structured_action",
        state=committed,
        settlement=result.facts,
        action_text=intent.raw_text,
    )


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


def _stream_timing(client: TestClient) -> tuple[float, float]:
    started = perf_counter()
    queued_at = None
    validated_at = None
    narrative_at = None
    with client.stream("POST", "/api/decree/stream", json={"decrees": []}) as response:
        for line in response.iter_lines():
            if line == "event: progress" and queued_at is None:
                queued_at = perf_counter()
            elif line == "event: narrative":
                narrative_at = perf_counter()
                break
            elif line.startswith("data: ") and '"stage": "validated"' in line:
                validated_at = perf_counter()
    assert queued_at is not None and validated_at is not None and narrative_at is not None
    return queued_at - started, narrative_at - validated_at


def _history_report() -> dict[str, object]:
    dataset = load_manifest("history-v1.json")
    queries = load_manifest("history-queries-v1.json")
    entries = build_history_entries(dataset)
    dataset_hash = history_dataset_sha256(entries)
    assert dataset_hash == dataset["dataset_sha256"]
    clear_history_query_cache()
    timings: list[float] = []
    query_results: list[dict[str, object]] = []
    history_gate_passed = True
    for case in queries["queries"]:
        expected = filter_history_entries(entries, **case["filters"])
        assert len(expected) == case["expected_count"]
        assert history_result_sha256(expected) == case["expected_sha256"]
        filter_history_entries_cached(
            entries,
            version_key=dataset_hash,
            **case["filters"],
        )
        case_timings: list[float] = []
        for _ in range(queries["iterations_per_query"]):
            started = perf_counter()
            actual = filter_history_entries_cached(
                entries,
                version_key=dataset_hash,
                **case["filters"],
            )
            elapsed = perf_counter() - started
            case_timings.append(elapsed)
            timings.append(elapsed)
        assert history_result_sha256(actual) == case["expected_sha256"]
        case_p95 = percentile_ms(case_timings, 0.95)
        history_gate_passed &= case_p95 <= queries["warm_cache_p95_ms"]
        query_results.append({
            "case_id": case["case_id"],
            "expected_sha256": case["expected_sha256"],
            "p95_ms": round(case_p95, 3),
        })
    p50_ms = percentile_ms(timings, 0.50)
    p95_ms = percentile_ms(timings, 0.95)
    expectation_hash = canonical_sha256([
        {
            "case_id": case["case_id"],
            "expected_count": case["expected_count"],
            "expected_sha256": case["expected_sha256"],
        }
        for case in queries["queries"]
    ])
    if not history_gate_passed:
        raise AssertionError("history warm-cache p95 exceeded its manifest threshold")
    return {
        "fixture": dataset["fixture_id"],
        "seed": dataset["seed"],
        "generator_version": dataset["generator_version"],
        "manifest_sha256": dataset["manifest_sha256"],
        "dataset_sha256": dataset_hash,
        "query_manifest_sha256": queries["manifest_sha256"],
        "query_expectations_sha256": expectation_hash,
        "entries": len(entries),
        "queries": len(queries["queries"]),
        "iterations_per_query": queries["iterations_per_query"],
        "strategy": "bounded-version-query-cache-v1",
        "cache_max_entries": HISTORY_QUERY_CACHE_MAX_ENTRIES,
        "latency_ms": {
            "p50": round(p50_ms, 3),
            "p95": round(p95_ms, 3),
        },
        "query_results": query_results,
        "gate": {
            "passed": history_gate_passed,
            "warm_cache_p95_ms_max": queries["warm_cache_p95_ms"],
        },
        "timing_boundary": "warm bounded-version query cache lookup",
    }


def _prompt_report(db_path: Path) -> dict[str, object]:
    manifest = load_manifest("prompt-regions-v1.json")
    base_context = _prompt_context(db_path)
    full_tokens: list[int] = []
    pruned_tokens: list[int] = []
    reductions: list[float] = []
    timings: list[float] = []
    fact_matches = 0
    for case in manifest["cases"]:
        facts = base_context.settlement.model_copy(update={
            "regional_targets": [case["target"]],
            "target_region_ids": [],
        })
        context = base_context.model_copy(update={
            "settlement": facts,
            "action_text": case["action_text"],
        })
        full_payload = context.model_dump(mode="json", exclude_none=True)
        full_count = estimate_prompt_tokens(context.model_dump_json(exclude_none=True))
        started = perf_counter()
        projection = project_narrative_context_for_prompt(context)
        timings.append(perf_counter() - started)
        pruned_count = estimate_prompt_tokens(projection.prompt_json())
        assert projection.detailed_region_names == case["expected_detailed_regions"]
        invariants_match = projection.context["settlement"] == full_payload["settlement"]
        invariants_match &= projection.context["source_versions"] == full_payload["source_versions"]
        invariants_match &= (
            projection.context["world_state"]["metrics"]
            == full_payload["world_state"]["metrics"]
        )
        fact_matches += int(invariants_match)
        full_tokens.append(full_count)
        pruned_tokens.append(pruned_count)
        reductions.append((full_count - pruned_count) / full_count * 100)
    median_reduction = statistics.median(reductions)
    projection_p95 = percentile_ms(timings, 0.95)
    prompt_gate_passed = (
        median_reduction >= manifest["minimum_median_token_reduction_percent"]
        and fact_matches == len(manifest["cases"])
        and projection_p95 < PROMPT_PROJECTION_P95_MAX_MS
    )
    if not prompt_gate_passed:
        raise AssertionError("prompt acceptance gate failed")
    return {
        "fixture": manifest["fixture_id"],
        "generator_version": manifest["generator_version"],
        "manifest_sha256": manifest["manifest_sha256"],
        "corpus_sha256": manifest["corpus_sha256"],
        "cases": len(manifest["cases"]),
        "tokenizer_id": manifest["tokenizer_id"],
        "provider_id": manifest["provider_id"],
        "median_full_tokens": round(statistics.median(full_tokens), 3),
        "median_pruned_tokens": round(statistics.median(pruned_tokens), 3),
        "median_reduction_percent": round(median_reduction, 3),
        "fact_matches": fact_matches,
        "projection_latency_ms": {
            "p50": round(percentile_ms(timings, 0.50), 3),
            "p95": round(projection_p95, 3),
        },
        "gate": {
            "passed": prompt_gate_passed,
            "minimum_median_token_reduction_percent": (
                manifest["minimum_median_token_reduction_percent"]
            ),
            "projection_p95_ms_max": PROMPT_PROJECTION_P95_MAX_MS,
        },
        "timing_boundary": "pure project_narrative_context_for_prompt call",
    }


def _sse_report() -> dict[str, object]:
    original = routes._execute_decree_core
    routes._execute_decree_core = _safe_local_core
    try:
        client = TestClient(app)
        _stream_timing(client)
        first_progress: list[float] = []
        safe_narrative: list[float] = []
        for _ in range(100):
            progress, narrative = _stream_timing(client)
            first_progress.append(progress)
            safe_narrative.append(narrative)
    finally:
        routes._execute_decree_core = original
    progress_p50 = percentile_ms(first_progress, 0.50)
    progress_p95 = percentile_ms(first_progress, 0.95)
    narrative_p50 = percentile_ms(safe_narrative, 0.50)
    narrative_p95 = percentile_ms(safe_narrative, 0.95)
    sse_gate_passed = (
        progress_p95 <= SSE_FIRST_PROGRESS_P95_MAX_MS
        and narrative_p95 <= SSE_VALIDATED_TO_NARRATIVE_P95_MAX_MS
    )
    if not sse_gate_passed:
        raise AssertionError("SSE latency gate failed")
    return {
        "benchmark_version": "sse-local-loopback-v1",
        "requests": 100,
        "transport": "in-process ASGI local loopback",
        "provider_network_wait_included": False,
        "first_progress_ms": {
            "p50": round(progress_p50, 3),
            "p95": round(progress_p95, 3),
        },
        "validated_to_safe_narrative_ms": {
            "p50": round(narrative_p50, 3),
            "p95": round(narrative_p95, 3),
        },
        "gate": {
            "passed": sse_gate_passed,
            "first_progress_p95_ms_max": SSE_FIRST_PROGRESS_P95_MAX_MS,
            "validated_to_safe_narrative_p95_ms_max": (
                SSE_VALIDATED_TO_NARRATIVE_P95_MAX_MS
            ),
        },
        "timing_boundary": (
            "request start to first progress; validated event to safe narrative event"
        ),
    }


def _storage_report(db_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    manifest = load_manifest("storage-v1.json")
    os.environ["STORAGE_RETENTION_RECENT_LIMIT"] = str(manifest["recent_limit"])
    started = perf_counter()
    fixture = generate_storage_fixture(db_path, manifest)
    generation_ms = round((perf_counter() - started) * 1000, 3)
    with closing(saves._connect()) as conn:
        pragmas = {
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
            "synchronous": conn.execute("PRAGMA synchronous").fetchone()[0],
            "page_size": conn.execute("PRAGMA page_size").fetchone()[0],
            "busy_timeout_ms": conn.execute("PRAGMA busy_timeout").fetchone()[0],
            "foreign_keys": conn.execute("PRAGMA foreign_keys").fetchone()[0],
        }
    result = maintenance.run_storage_maintenance("manual")
    assert result.status == "success"
    post_vacuum_ratio = result.size_after / result.size_before
    storage_gate_passed = post_vacuum_ratio <= manifest["max_post_vacuum_ratio"]
    if not storage_gate_passed:
        raise AssertionError("storage post-VACUUM ratio exceeded its manifest threshold")
    return (
        {
            "fixture": manifest["fixture_id"],
            "seed": manifest["seed"],
            "generator_version": manifest["generator_version"],
            "manifest_sha256": manifest["manifest_sha256"],
            "payload_rule_sha256": manifest["payload_rule_sha256"],
            "snapshots": sum(len(items) for items in fixture.branches.values()),
            "branches": {
                key: len(value) for key, value in fixture.branches.items()
            },
            "bookmarks": len(fixture.bookmark_version_ids),
            "average_snapshot_bytes": round(statistics.mean(fixture.serialized_sizes), 3),
            "fixture_generation_ms": generation_ms,
            "maintenance_duration_ms": result.duration_ms,
            "size_before": result.size_before,
            "size_after": result.size_after,
            "post_vacuum_ratio": round(post_vacuum_ratio, 6),
            "reclaimed_bytes": result.reclaimed_bytes,
            "gate": {
                "passed": storage_gate_passed,
                "max_post_vacuum_ratio": manifest["max_post_vacuum_ratio"],
            },
            "timing_boundary": (
                "fixture generation and run_storage_maintenance(retention plus VACUUM)"
            ),
        },
        pragmas,
    )


def main() -> int:
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        history = _history_report()
        prompt = _prompt_report(root / "prompt.db")
        sse = _sse_report()
        storage, pragmas = _storage_report(root / "storage.db")
    all_gates_passed = all(
        bool(section["gate"]["passed"])
        for section in (storage, sse, history, prompt)
    )
    if not all_gates_passed:
        raise AssertionError("one or more acceptance gates failed")
    report = {
        "report_version": 1,
        "change": "backend-storage-engine-streaming-optimization",
        "measured_on": date.today().isoformat(),
        "command": "python -m tests.benchmarks.run_acceptance",
        "all_gates_passed": all_gates_passed,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu": (
                platform.processor()
                or os.getenv("PROCESSOR_IDENTIFIER")
                or platform.machine()
            ),
            "logical_cpu_count": os.cpu_count(),
            "sqlite": sqlite3.sqlite_version,
        },
        "sqlite_pragmas": pragmas,
        "storage": storage,
        "sse": sse,
        "history": history,
        "prompt": prompt,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
