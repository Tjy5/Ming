from __future__ import annotations

import json
import statistics
from pathlib import Path
from time import perf_counter

from ai.narrative_context import (
    MAX_DISTANT_REGION_SUMMARY_TOKENS,
    PROMPT_TOKENIZER_ID,
    build_narrative_context,
    estimate_prompt_tokens,
    project_narrative_context_for_prompt,
)
from api.history_service import (
    clear_history_query_cache,
    filter_history_entries,
    filter_history_entries_cached,
)
from db import saves, worlds
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal
from models.world import RegionEntity, new_client_action_id
from tests.benchmarks.manifests import (
    build_history_entries,
    canonical_sha256,
    history_dataset_sha256,
    history_result_sha256,
    load_manifest,
    percentile_ms,
    prompt_case_input_sha256,
    storage_payload_rule_sha256,
)


def _prompt_context(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "prompt-regions-v1.db")
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


def test_storage_manifest_has_canonical_seed_and_payload_hash():
    manifest = load_manifest("storage-v1.json")
    assert manifest["seed"] == 135204
    assert sum(manifest["branch_snapshot_counts"].values()) == 1000
    assert manifest["payload_rule_sha256"] == storage_payload_rule_sha256(manifest)
    assert sum(len(indexes) for indexes in manifest["bookmark_local_indexes"].values()) == 20


def test_recorded_acceptance_report_is_hash_linked_and_all_gates_passed():
    report_path = Path(__file__).with_name("benchmarks") / "acceptance-results.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    storage = load_manifest("storage-v1.json")
    history = load_manifest("history-v1.json")
    history_queries = load_manifest("history-queries-v1.json")
    prompt = load_manifest("prompt-regions-v1.json")
    query_expectations_sha256 = canonical_sha256([
        {
            "case_id": case["case_id"],
            "expected_count": case["expected_count"],
            "expected_sha256": case["expected_sha256"],
        }
        for case in history_queries["queries"]
    ])

    assert report["all_gates_passed"] is True
    assert all(
        report[section]["gate"]["passed"] is True
        for section in ("storage", "sse", "history", "prompt")
    )
    assert report["storage"]["fixture"] == storage["fixture_id"]
    assert report["storage"]["seed"] == storage["seed"]
    assert report["storage"]["generator_version"] == storage["generator_version"]
    assert report["storage"]["manifest_sha256"] == storage["manifest_sha256"]
    assert report["storage"]["payload_rule_sha256"] == storage["payload_rule_sha256"]
    assert report["history"]["fixture"] == history["fixture_id"]
    assert report["history"]["seed"] == history["seed"]
    assert report["history"]["generator_version"] == history["generator_version"]
    assert report["history"]["manifest_sha256"] == history["manifest_sha256"]
    assert report["history"]["dataset_sha256"] == history["dataset_sha256"]
    assert report["history"]["query_manifest_sha256"] == (
        history_queries["manifest_sha256"]
    )
    assert report["history"]["query_expectations_sha256"] == (
        query_expectations_sha256
    )
    assert report["prompt"]["fixture"] == prompt["fixture_id"]
    assert report["prompt"]["generator_version"] == prompt["generator_version"]
    assert report["prompt"]["manifest_sha256"] == prompt["manifest_sha256"]
    assert report["prompt"]["corpus_sha256"] == prompt["corpus_sha256"]
    assert report["prompt"]["tokenizer_id"] == prompt["tokenizer_id"]
    assert report["prompt"]["provider_id"] == prompt["provider_id"]


def test_history_manifests_are_reproducible_and_meet_query_p95():
    dataset = load_manifest("history-v1.json")
    query_manifest = load_manifest("history-queries-v1.json")
    entries = build_history_entries(dataset)

    assert dataset["seed"] == 135205
    assert len(entries) == 10_000
    dataset_hash = history_dataset_sha256(entries)
    assert dataset_hash == dataset["dataset_sha256"]
    clear_history_query_cache()
    for case in query_manifest["queries"]:
        expected = filter_history_entries(entries, **case["filters"])
        assert len(expected) == case["expected_count"]
        assert history_result_sha256(expected) == case["expected_sha256"]
        filter_history_entries_cached(
            entries,
            version_key=dataset_hash,
            **case["filters"],
        )
        timings: list[float] = []
        for _ in range(query_manifest["iterations_per_query"]):
            started = perf_counter()
            actual = filter_history_entries_cached(
                entries,
                version_key=dataset_hash,
                **case["filters"],
            )
            timings.append(perf_counter() - started)
        assert history_result_sha256(actual) == case["expected_sha256"]
        assert percentile_ms(timings, 0.95) <= query_manifest["warm_cache_p95_ms"]


def test_prompt_regions_corpus_reduces_tokens_without_changing_facts(
    monkeypatch,
    tmp_path,
):
    manifest = load_manifest("prompt-regions-v1.json")
    assert manifest["tokenizer_id"] == PROMPT_TOKENIZER_ID
    assert len(manifest["cases"]) == 30
    assert manifest["corpus_sha256"] == canonical_sha256([
        {key: value for key, value in case.items() if key != "input_sha256"}
        for case in manifest["cases"]
    ])

    base_context = _prompt_context(monkeypatch, tmp_path)
    reductions: list[float] = []
    latencies: list[float] = []
    for case in manifest["cases"]:
        assert prompt_case_input_sha256(case) == case["input_sha256"]
        facts = base_context.settlement.model_copy(update={
            "regional_targets": [case["target"]],
            "target_region_ids": [],
        })
        context = base_context.model_copy(update={
            "settlement": facts,
            "action_text": case["action_text"],
        })
        full_payload = context.model_dump(mode="json", exclude_none=True)
        full_tokens = estimate_prompt_tokens(context.model_dump_json(exclude_none=True))
        started = perf_counter()
        projection = project_narrative_context_for_prompt(context)
        latencies.append(perf_counter() - started)
        pruned_tokens = estimate_prompt_tokens(projection.prompt_json())

        assert projection.mode == "regional"
        assert projection.detailed_region_names == case["expected_detailed_regions"]
        assert projection.distant_region_summary_tokens <= (
            MAX_DISTANT_REGION_SUMMARY_TOKENS
        )
        for path in manifest["invariant_paths"]:
            if path == "world_state.metrics":
                assert projection.context["world_state"]["metrics"] == (
                    full_payload["world_state"]["metrics"]
                )
            else:
                assert projection.context.get(path) == full_payload.get(path)
        reductions.append((full_tokens - pruned_tokens) / full_tokens * 100)

    assert statistics.median(reductions) >= (
        manifest["minimum_median_token_reduction_percent"]
    )
    assert percentile_ms(latencies, 0.95) < 100
