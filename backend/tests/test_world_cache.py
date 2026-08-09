from __future__ import annotations

import pytest

from api import state as api_state
from db import saves, worlds
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, MetricWorldDelta
from models.world import new_client_action_id, new_delta_id


@pytest.fixture(autouse=True)
def _restore_cache():
    old_state = api_state._state
    old_ref = api_state._get_world_head_ref()
    try:
        yield
    finally:
        api_state._state = old_state
        api_state._world_head_cache.restore_ref(old_ref)


def test_legacy_direct_state_assignment_remains_visible_through_cache_facade():
    state = create_initial_state()
    api_state._state = state

    assert api_state._get_state() is state


def test_cache_publish_failure_can_reload_the_committed_head(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "cache.db")
    saves.init_db()
    initial = create_initial_state()
    root = worlds.create_game_with_root(initial)
    root_snapshot = worlds.load_version(root.version_id)
    api_state._publish_world_head(root_snapshot.state, root)

    changed = root_snapshot.state.model_copy(deep=True)
    changed.civil_morale += 4
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="开仓赈济",
        action_kind="decree",
    )
    proposal = AdjudicationProposal(
        result_tier="success",
        key_factors=["赈济及时"],
        immediate_changes=["民心改善"],
        deltas=[
            MetricWorldDelta(
                delta_id=new_delta_id(),
                target_scope="world",
                field="civil_morale",
                operation="increment",
                before_value=root_snapshot.state.civil_morale,
                value=4,
            ),
        ],
    )
    committed = worlds.commit_settlement(intent, changed, proposal)

    with monkeypatch.context() as patch:
        def fail_publish(*args, **kwargs):
            raise RuntimeError("injected cache publish failure")

        patch.setattr(api_state._world_head_cache, "publish", fail_publish)
        with pytest.raises(RuntimeError, match="cache publish"):
            api_state._publish_world_head(changed, committed.version)

    assert api_state._get_state().civil_morale == initial.civil_morale
    assert api_state._get_world_head_ref() == root
    reloaded = api_state._reload_world_head(root.game_id, root.branch_id)
    assert reloaded.civil_morale == changed.civil_morale
    assert api_state._get_world_head_ref() == committed.version
