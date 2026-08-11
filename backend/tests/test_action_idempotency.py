from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from db import saves, worlds
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, MetricWorldDelta
from models.world import new_client_action_id, new_delta_id


def _store(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "idempotency.db")
    saves.init_db()
    initial = create_initial_state()
    root = worlds.create_game_with_root(initial)
    return worlds.load_version(root.version_id).state, root


def _intent(root, action_id, text="兴修水利"):
    return ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=action_id,
        raw_text=text,
        action_kind="decree",
    )


def _proposal(before, value=2):
    return AdjudicationProposal(
        result_tier="success",
        key_factors=["水工得力"],
        immediate_changes=["民心改善"],
        deltas=[
            MetricWorldDelta(
                delta_id=new_delta_id(),
                target_scope="world",
                field="civil_morale",
                operation="increment",
                before_value=before,
                value=value,
            ),
        ],
    )


def test_same_action_identity_replays_without_second_settlement(monkeypatch, tmp_path):
    initial, root = _store(monkeypatch, tmp_path)
    intent = _intent(root, new_client_action_id())
    changed = initial.model_copy(deep=True)
    changed.civil_morale += 2
    proposal = _proposal(initial.civil_morale)

    first = worlds.commit_settlement(intent, changed, proposal)
    replay = worlds.commit_settlement(intent, changed, proposal)

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.version == first.version
    assert replay.facts == first.facts
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 2


def test_same_identity_with_different_payload_is_conflict(monkeypatch, tmp_path):
    initial, root = _store(monkeypatch, tmp_path)
    action_id = new_client_action_id()
    changed = initial.model_copy(deep=True)
    changed.civil_morale += 2
    worlds.commit_settlement(
        _intent(root, action_id),
        changed,
        _proposal(initial.civil_morale),
    )

    conflicting = _intent(root, action_id, text="取消水利工程")
    with pytest.raises(worlds.IdempotencyConflictError) as exc_info:
        worlds.commit_settlement(
            conflicting,
            changed,
            _proposal(initial.civil_morale),
        )

    assert exc_info.value.code == "idempotency_conflict"
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1


def test_stale_parent_is_legal_conflict_and_leaves_head_unchanged(monkeypatch, tmp_path):
    initial, root = _store(monkeypatch, tmp_path)
    changed = initial.model_copy(deep=True)
    changed.civil_morale += 2
    committed = worlds.commit_settlement(
        _intent(root, new_client_action_id()),
        changed,
        _proposal(initial.civil_morale),
    )

    stale = _intent(root, new_client_action_id(), text="旧页面再次提交")
    with pytest.raises(worlds.StaleParentVersionError) as exc_info:
        worlds.commit_settlement(stale, changed, _proposal(initial.civil_morale))

    assert exc_info.value.code == "stale_parent_version"
    assert worlds.get_branch_head(root.game_id, root.branch_id) == committed.version
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1


def test_concurrent_double_click_commits_once_and_replays_once(monkeypatch, tmp_path):
    initial, root = _store(monkeypatch, tmp_path)
    intent = _intent(root, new_client_action_id(), text="并发双击")
    changed = initial.model_copy(deep=True)
    changed.civil_morale += 2
    proposal = _proposal(initial.civil_morale)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: worlds.commit_settlement(intent, changed, proposal),
                range(2),
            ),
        )

    assert sorted(result.replayed for result in results) == [False, True]
    assert results[0].version == results[1].version
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 2
