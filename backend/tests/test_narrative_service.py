from __future__ import annotations

import asyncio

from db import narrative_memory, saves, worlds
from ai.narrative_context import build_narrative_context
from ai.narrative_registry import iter_narrative_paths
from ai.narrative_service import build_narrative_prompt, generate_narrative_artifact
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal
from models.world import new_client_action_id


def _context(monkeypatch, tmp_path, *, state_update=None):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "narrative-service.db")
    saves.init_db()
    initial = create_initial_state()
    if state_update:
        initial = initial.model_copy(update=state_update)
    root = worlds.create_game_with_root(initial)
    parent = worlds.load_version(root.version_id).state
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="继续当前世界",
        action_kind="decree",
    )
    proposal = AdjudicationProposal(
        result_tier="success",
        key_factors=["当前事实允许行动"],
        immediate_changes=["世界继续演化"],
        execution_status="completed",
    )
    result = worlds.commit_settlement(intent, parent, proposal)
    state = worlds.load_version(result.version.version_id).state
    context = build_narrative_context(
        path_id="structured_action",
        state=state,
        settlement=result.facts,
        action_text=intent.raw_text,
    )
    return root, state, context


def test_runtime_prompt_preserves_historical_persona(monkeypatch, tmp_path):
    _root, _state, context = _context(monkeypatch, tmp_path)

    _prompt, system = build_narrative_prompt(context)

    assert "元末" in system
    assert "至正" in system
    assert "洪武皇帝" in system
    assert "臣僚" in system


def test_threshold_tone_violation_triggers_repair(monkeypatch, tmp_path):
    _root, state, context = _context(
        monkeypatch,
        tmp_path,
        state_update={"civil_morale": 10},
    )
    repairs: list[str | None] = []

    async def generate(_context, repair):
        repairs.append(repair)
        if repair is None:
            return "城中歌舞升平，民心安泰。"
        return "民怨沸腾，流民四起，盗匪横行。"

    result = asyncio.run(generate_narrative_artifact(
        context=context,
        state=state,
        generate=generate,
    ))

    assert result.narrative_status == "repaired"
    assert "threshold_tone_violation" in result.finding_codes
    assert repairs[1] is not None and "民心崩溃预警" in repairs[1]
    assert "歌舞升平" not in result.text


def test_service_repairs_full_buffer_before_returning_any_chunk(monkeypatch, tmp_path):
    _root, state, context = _context(monkeypatch, tmp_path)
    calls: list[str | None] = []

    async def stream(_context):
        yield "当前为9999年，"
        yield "主角死亡，游戏结束。"

    async def generate(_context, repair):
        calls.append(repair)
        return "世界仍按已提交事实继续演化。"

    result = asyncio.run(
        generate_narrative_artifact(
            context=context,
            state=state,
            stream=stream,
            generate=generate,
        ),
    )

    assert result.narrative_status == "repaired"
    assert result.chunks == ["世界仍按已提交事实继续演化。"]
    assert "9999" not in result.text
    assert "主角死亡" not in result.text
    assert calls and calls[0] is not None
    assert result.artifact_id is not None
    assert result.progress_stages == [
        "context_ready", "generating", "validating", "repairing", "validated",
    ]


def test_service_uses_labeled_settlement_facts_when_generation_stays_invalid(
    monkeypatch,
    tmp_path,
):
    root, state, context = _context(monkeypatch, tmp_path)
    before_versions = worlds.list_versions(root.game_id, root.branch_id)

    async def generate(_context, _repair):
        return "如今9999年，主角死亡，游戏结束。"

    result = asyncio.run(
        generate_narrative_artifact(
            context=context,
            state=state,
            generate=generate,
        ),
    )

    assert result.narrative_status == "fallback_facts"
    assert "结算编号" in result.text
    assert str(context.settlement_id) in result.text
    assert "9999" not in result.text
    assert worlds.list_versions(root.game_id, root.branch_id) == before_versions
    current = narrative_memory.get_current_artifact(
        context.settlement.game_id,
        context.settlement.branch_id,
        context.settlement.settlement_id,
        "structured_action",
    )
    assert current is not None
    assert current.text == result.text


def test_service_never_accepts_semantically_truncated_sanitized_text(monkeypatch, tmp_path):
    _root, state, context = _context(monkeypatch, tmp_path)

    async def generate(_context, _repair):
        return "如今9999年。世界仍在继续。"

    result = asyncio.run(
        generate_narrative_artifact(
            context=context,
            state=state,
            generate=generate,
        ),
    )

    assert result.narrative_status == "fallback_facts"
    assert "9999" not in result.text
    assert "结算编号" in result.text


def test_provider_failure_uses_one_attempt_and_safe_diagnostic(monkeypatch, tmp_path):
    _root, state, context = _context(monkeypatch, tmp_path)
    calls = 0

    async def generate(_context, _repair):
        nonlocal calls
        calls += 1
        raise RuntimeError("secret provider body")

    result = asyncio.run(
        generate_narrative_artifact(
            context=context,
            state=state,
            generate=generate,
        ),
    )

    assert calls == 1
    assert result.narrative_status == "fallback_facts"
    assert "provider_generation_failed" in result.finding_codes
    assert "secret provider body" not in result.model_dump_json()
    assert result.context_schema_version == context.schema_version
    assert result.source_versions["narrative_registry"] == "narrative-paths-v1"
    assert result.outcome_stage == "fallback_facts"
    assert result.duration_ms >= 0
    artifact = narrative_memory.get_current_artifact(
        context.settlement.game_id,
        context.settlement.branch_id,
        context.settlement.settlement_id,
        "structured_action",
    )
    assert artifact is not None
    assert artifact.context_schema_version == context.schema_version
    assert artifact.source_versions == result.source_versions
    assert artifact.outcome_stage == "fallback_facts"
    assert artifact.duration_ms == result.duration_ms
    assert "secret provider body" not in artifact.model_dump_json()


def test_dynamic_registered_entity_is_not_rejected_as_invented(monkeypatch, tmp_path):
    _root, state, context = _context(monkeypatch, tmp_path)
    dynamic = next(
        entity for entity in context.entities if entity.display_name == "主角"
    )

    async def generate(_context, _repair):
        return f"{dynamic.display_name}：世界将沿玩家选择继续。"

    result = asyncio.run(
        generate_narrative_artifact(
            context=context,
            state=state,
            generate=generate,
        ),
    )
    assert result.narrative_status == "validated"


def test_every_registered_path_returns_safe_traceable_diagnostics(monkeypatch, tmp_path):
    _root, state, committed_context = _context(monkeypatch, tmp_path)
    person_id = state.player_world_status.player_character_id
    assert person_id is not None

    async def generate(_context, _repair):
        return "当前世界依据已提交事实继续演化。"

    for path in iter_narrative_paths():
        context = build_narrative_context(
            path_id=path.path_id,
            state=state,
            settlement=committed_context.settlement if path.settlement_required else None,
            person_entity_id=person_id if path.person_scoped else None,
            topic_id=f"diagnostic:{path.path_id}",
            action_text="验证路径诊断",
        )
        request_id = f"diagnostic-{path.path_id}"
        result = asyncio.run(generate_narrative_artifact(
            context=context,
            state=state,
            generate=generate,
            request_id=request_id,
        ))

        assert result.path_id == path.path_id
        assert result.request_id == request_id
        assert result.context_version_id == context.version_id
        assert result.context_schema_version == context.schema_version
        assert result.source_versions["narrative_registry"] == "narrative-paths-v1"
        assert result.source_versions["world_state_projection"] == (
            "world-state-projection-v1"
        )
        assert result.outcome_stage == result.narrative_status
        assert result.duration_ms >= 0
        assert result.attempt_count == 1
        if path.settlement_required:
            assert result.settlement_id == committed_context.settlement_id
            assert result.artifact_id is not None
            artifact = narrative_memory.get_current_artifact(
                context.game_id,
                context.branch_id,
                context.settlement_id,
                path.path_id,
            )
            assert artifact is not None
            assert artifact.request_id == request_id
            assert artifact.path_id == path.path_id
        else:
            assert result.settlement_id is None
            assert result.artifact_id is None
