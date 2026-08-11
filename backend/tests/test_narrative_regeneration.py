from __future__ import annotations

import asyncio

from ai.base import GenerationResult
from api import narrative_routes
from api import state as api_state
from db import narrative_memory, saves, worlds
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal
from models.world import new_client_action_id
from fakes import FakeProvider


class _NarrativeProvider(FakeProvider):
    def __init__(self):
        self.calls = 0

    async def generate_text_once(self, *args, **kwargs):
        self.calls += 1
        return GenerationResult(text="行动已按当前世界事实推进，新的选择仍然开放。")


def _settlement(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "narrative-regeneration.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    state = worlds.load_version(root.version_id).state
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="建立新的治理路线",
        action_kind="freeform",
    )
    proposal = AdjudicationProposal(
        result_tier="success",
        key_factors=["当前分支允许"],
        immediate_changes=["路线已改变"],
        execution_status="completed",
    )
    result = worlds.commit_settlement(intent, state, proposal)
    return root, result


def test_regeneration_only_adds_artifact_and_never_resettles(monkeypatch, tmp_path):
    root, committed = _settlement(monkeypatch, tmp_path)
    provider = _NarrativeProvider()
    monkeypatch.setattr(api_state, "_provider", provider)
    before_versions = worlds.list_versions(root.game_id, root.branch_id)
    before_settlements = worlds.list_settlements(root.game_id, root.branch_id)

    first = asyncio.run(
        narrative_routes.regenerate_narrative(
            committed.facts.settlement_id,
            narrative_routes.NarrativeRegenerationRequest(
                path_id="unified_action",
                topic_id="route-change",
            ),
        ),
    )
    second = asyncio.run(
        narrative_routes.regenerate_narrative(
            committed.facts.settlement_id,
            narrative_routes.NarrativeRegenerationRequest(
                path_id="unified_action",
                topic_id="route-change",
            ),
        ),
    )

    assert first.artifact_id != second.artifact_id
    assert provider.calls == 2
    assert worlds.list_versions(root.game_id, root.branch_id) == before_versions
    assert worlds.list_settlements(root.game_id, root.branch_id) == before_settlements
    assert len(narrative_memory.list_artifacts(
        root.game_id,
        root.branch_id,
        committed.facts.settlement_id,
    )) == 2
    current = narrative_memory.get_current_artifact(
        root.game_id,
        root.branch_id,
        committed.facts.settlement_id,
        "unified_action",
    )
    assert current is not None
    assert current.artifact_id == second.artifact_id
