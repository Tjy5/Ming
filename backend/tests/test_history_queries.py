from __future__ import annotations

import asyncio
from types import SimpleNamespace
from time import perf_counter

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ai.provider import ResilientProvider
from api import routes
from api import state as api_state
from api import history_service
from api.history_service import (
    append_history_entry,
    clear_history_query_cache,
    filter_history_entries,
    filter_history_entries_cached,
    history_provinces,
)
from db import saves, worlds
from models.game import GameState, HistoryEntry, create_initial_state
from models.enums import DecreeType
from models.game import StructuredDecree
from models.settlement import ActionIntent, AdjudicationProposal
from models.world import RegionEntity, new_client_action_id
from fakes import FakeProvider
from main import app


@pytest.fixture
def isolated_history(monkeypatch, tmp_path):
    old_state = api_state._state
    old_ref = api_state._get_world_head_ref()
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "history.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    clear_history_query_cache()
    try:
        yield
    finally:
        clear_history_query_cache()
        api_state._state = old_state
        api_state._world_head_cache.restore_ref(old_ref)


def _publish_root(state: GameState):
    root = worlds.create_game_with_root(state)
    snapshot = worlds.load_version(root.version_id)
    api_state._world_head_cache.publish(snapshot.state, snapshot.ref)
    return root


def test_generic_request_validation_uses_error_response(isolated_history):
    with TestClient(app) as client:
        response = client.get("/api/history", params={"month": "not-an-integer"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error_code"] == "request_validation_error"
    assert detail["message"] == "请求参数校验失败"
    assert detail["details"]["errors"][0]["loc"][-1] == "month"


def test_history_query_cache_is_version_scoped_and_bounded(monkeypatch):
    entries = [
        HistoryEntry(
            sequence=index,
            year=1356,
            month=1,
            decree_type="domestic",
            category="domestic",
        )
        for index in range(3)
    ]
    calls = 0
    original = history_service.filter_history_entries

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    clear_history_query_cache()
    monkeypatch.setattr(history_service, "filter_history_entries", counted)
    first = filter_history_entries_cached(
        entries,
        version_key="version-1",
        category="domestic",
    )
    repeated = filter_history_entries_cached(
        entries,
        version_key="version-1",
        category="domestic",
    )
    filter_history_entries_cached(
        entries,
        version_key="version-2",
        category="domestic",
    )

    assert first == repeated
    assert calls == 2

    for index in range(history_service.HISTORY_QUERY_CACHE_MAX_ENTRIES + 5):
        filter_history_entries_cached(entries, version_key=f"bounded-{index}")
    assert len(history_service._history_query_cache) == (
        history_service.HISTORY_QUERY_CACHE_MAX_ENTRIES
    )


def _commit_history(parent, state: GameState, description: str):
    changed = state.model_copy(deep=True)
    append_history_entry(changed, decree_type="other", decree_desc=description)
    result = worlds.commit_settlement(
        ActionIntent(
            game_id=parent.game_id,
            branch_id=parent.branch_id,
            expected_parent_version_id=parent.version_id,
            client_action_id=new_client_action_id(),
            raw_text=description,
            action_kind="other",
        ),
        changed,
        AdjudicationProposal(
            result_tier="success",
            key_factors=["history isolation fixture"],
            immediate_changes=["history"],
        ),
    )
    return result.version, worlds.load_version(result.version.version_id).state


def test_legacy_history_metadata_migrates_in_list_order():
    payload = create_initial_state().model_dump(mode="json")
    payload["history_log"] = [
        {"year": 1351, "month": 1, "decree_type": "tax_increase"},
        {"year": 1351, "month": 2, "decree_type": "personnel"},
        {"year": 1351, "month": 3, "decree_type": "disaster_relief"},
        {"year": 1351, "month": 4, "decree_type": "unknown"},
    ]

    notes = saves._migrate_save(payload)
    state = GameState.model_validate(payload)

    assert [entry.sequence for entry in state.history_log] == [0, 1, 2, 3]
    assert [entry.category for entry in state.history_log] == [
        "domestic", "personnel", "disaster", "other",
    ]
    assert all(entry.provinces == [] for entry in state.history_log)
    assert any("历史记录" in note for note in notes)


def test_history_provinces_use_only_canonical_targets_and_settlement_deltas(
    isolated_history,
):
    root = worlds.create_game_with_root(create_initial_state())
    state = worlds.load_version(root.version_id).state
    region_ids = {
        entity.legacy_name or entity.display_name: entity_id
        for entity_id, entity in state.entity_registry.items()
        if isinstance(entity, RegionEntity)
    }

    result = history_provinces(
        state,
        target_region_id=region_ids["应天"],
        target_entity_ids=[region_ids["太平"], region_ids["应天"]],
        settlement_deltas=[
            SimpleNamespace(target_scope="region", target_id=region_ids["镇江"]),
            SimpleNamespace(target_scope="world", target_id=None),
        ],
    )

    assert result == ["应天", "太平", "镇江"]
    assert history_provinces(state, structured_target="河南江北行省") == [
        "两淮", "应天", "太平", "镇江", "平江",
    ]
    assert history_provinces(state, structured_target="应天赈灾") == []


def test_combined_filters_aliases_stable_sort_and_page(isolated_history):
    state = create_initial_state()
    state.history_log = [
        HistoryEntry(
            sequence=2,
            year=1352,
            month=4,
            decree_type="recruit_troops",
            provinces=["应天"],
        ),
        HistoryEntry(
            sequence=0,
            year=1351,
            month=12,
            decree_type="tax_increase",
            provinces=["应天"],
        ),
        HistoryEntry(
            sequence=1,
            year=1352,
            month=4,
            decree_type="disband_troops",
            provinces=["应天", "太平"],
        ),
        HistoryEntry(
            sequence=3,
            year=1352,
            month=4,
            decree_type="recruit_troops",
            provinces=["杭州"],
        ),
    ]
    _publish_root(state)

    result = asyncio.run(routes.get_history(
        year=1352,
        month=4,
        category="军事",
        province="应天",
        page=1,
        limit=20,
    ))

    assert result["total"] == 2
    assert result["offset"] == 0
    assert result["page"] == 1
    assert [entry["sequence"] for entry in result["entries"]] == [1, 2]


def test_structured_decree_persists_canonical_category_and_province(isolated_history):
    api_state._state = create_initial_state()
    api_state._provider = ResilientProvider(FakeProvider(), timeout=1, retries=1)

    asyncio.run(routes.execute_decree(routes.DecreeRequest(
        decrees=[
            StructuredDecree(
                type=DecreeType.DISASTER_RELIEF,
                target="应天",
            ),
        ],
    )))
    result = asyncio.run(routes.get_history())

    entry = result["entries"][-1]
    assert entry["category"] == "disaster"
    assert entry["provinces"] == ["应天"]


def test_legacy_offset_mode_clamps_and_reports_normalized_page(isolated_history):
    state = create_initial_state()
    state.history_log = [
        HistoryEntry(sequence=index, year=1350, month=1, decree_type="other")
        for index in range(130)
    ]
    _publish_root(state)

    first = asyncio.run(routes.get_history(offset=-5, limit=0))
    capped = asyncio.run(routes.get_history(offset=105, limit=500))

    assert (first["offset"], first["limit"], first["page"]) == (0, 1, 1)
    assert (capped["offset"], capped["limit"], capped["page"]) == (105, 100, 2)
    assert len(capped["entries"]) == 25


@pytest.mark.parametrize(
    "kwargs",
    [
        {"year": 0},
        {"month": 13},
        {"category": "unknown"},
        {"province": ""},
        {"page": 0},
        {"page": 1, "offset": 1},
        {"year": 1352, "offset": -1},
        {"year": 1352, "limit": 101},
    ],
)
def test_strict_mode_rejects_invalid_queries(isolated_history, kwargs):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.get_history(**kwargs))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "invalid_history_query"


def test_no_head_returns_empty_without_creating_storage(isolated_history):
    result = asyncio.run(routes.get_history(year=1352))

    assert result["total"] == 0
    assert result["entries"] == []
    with saves._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0] == 0


def test_query_does_not_leak_other_games_or_branches(isolated_history):
    state_a = create_initial_state()
    append_history_entry(state_a, decree_type="tax_increase", decree_desc="game-a")
    root_a = worlds.create_game_with_root(state_a)
    snapshot_a = worlds.load_version(root_a.version_id)

    state_b = create_initial_state()
    append_history_entry(state_b, decree_type="recruit_troops", decree_desc="game-b")
    worlds.create_game_with_root(state_b)

    fork = worlds.create_branch_from_version(root_a.version_id)
    fork_state = worlds.load_version(fork.version_id).state
    _commit_history(fork, fork_state, "fork-only")
    api_state._world_head_cache.publish(snapshot_a.state, snapshot_a.ref)

    result = asyncio.run(routes.get_history())

    assert [entry["decree_desc"] for entry in result["entries"]] == ["game-a"]


def test_corrupt_current_head_returns_structured_storage_error(isolated_history):
    root = _publish_root(create_initial_state())
    with saves._connect() as conn:
        conn.execute(
            "UPDATE versions SET state_json = ? WHERE id = ?",
            ('{"broken":', str(root.version_id)),
        )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.get_history())

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["error_code"] == "history_store_error"


def test_ten_thousand_entry_combined_filters_have_correct_results_and_p95():
    categories = (
        "domestic", "military", "diplomacy", "personnel", "disaster", "other",
    )
    provinces = tuple(f"region-{index}" for index in range(20))
    entries = [
        HistoryEntry(
            sequence=index,
            year=1345 + index % 10,
            month=index % 12 + 1,
            decree_type="benchmark",
            category=categories[index % len(categories)],
            provinces=[provinces[index % len(provinces)]],
        )
        for index in range(10_000)
    ]
    expected = [
        entry
        for entry in entries
        if entry.year == 1347
        and entry.month == 3
        and entry.category == "diplomacy"
        and "region-2" in entry.provinces
    ]
    filter_history_entries(entries, year=1347, month=3, category="diplomacy", province="region-2")
    timings: list[float] = []
    for _ in range(100):
        started = perf_counter()
        result = filter_history_entries(
            entries,
            year=1347,
            month=3,
            category="diplomacy",
            province="region-2",
        )
        timings.append(perf_counter() - started)

    assert [entry.sequence for entry in result] == [entry.sequence for entry in expected]
    p95 = sorted(timings)[94]
    assert p95 < 0.200
