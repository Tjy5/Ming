import asyncio
import os

import pytest
from fastapi import HTTPException

from ai.provider import ResilientProvider
from ai.base import GenerationResult
from fakes import FakeProvider
from api import routes
from api import state as api_state
from api import settings_routes
from api import assembly_routes
from db import narrative_memory, saves, worlds
from engine.core import inject_script_events
from models.enums import (
    AssemblyPhase,
    DecreeType,
    MemorialStatus,
    MinisterStatus,
    PersonnelAction,
)
from models.game import (
    AssemblyParticipant,
    CourtAssembly,
    DebateMinister,
    DebateResult,
    FreeformResult,
    GameTime,
    HistoryEntry,
    Memorial,
    PolicySuggestion,
    StructuredDecree,
    create_initial_state,
)


@pytest.fixture(autouse=True)
def _restore_route_globals():
    old_state = api_state._state
    old_provider = api_state._provider
    try:
        yield
    finally:
        api_state._state = old_state
        api_state._provider = old_provider


def _fake_provider():
    return ResilientProvider(FakeProvider(), timeout=1, retries=1)


def _governance_opening_state():
    """治理开局态：拨到切换点 1356-03 + 注入脚本事件 + 激活已入仕大臣。

    （新档开局 1328-10 为跑团开局：无治理脚本事件、大臣均未入仕。）
    """
    state = create_initial_state()
    state.time = GameTime(year=1356, month=3, era_name="至正", era_year=16)
    inject_script_events(state)
    for m in state.ministers:
        if m.status == MinisterStatus.NOT_YET_ENTERED:
            m.status = MinisterStatus.ACTIVE if m.positions else MinisterStatus.IDLE
    return state


def test_execute_decree_is_atomic_when_later_decree_fails_precondition():
    api_state._provider = _fake_provider()
    api_state._state = create_initial_state()
    api_state._state.civil_morale = 12  # HARSH_PUNISHMENT passes (>5), TAX_INCREASE fails after (civil_morale drops to ~2)
    before = api_state._state.model_dump()

    req = routes.DecreeRequest(
        decrees=[
            StructuredDecree(type=DecreeType.HARSH_PUNISHMENT),
            StructuredDecree(type=DecreeType.TAX_INCREASE),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(req))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "precondition_failed"
    assert api_state._state is not None
    assert api_state._state.model_dump() == before


def test_personnel_target_must_exist():
    api_state._provider = _fake_provider()
    api_state._state = create_initial_state()
    before = api_state._state.model_dump()

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
    assert api_state._state is not None
    assert api_state._state.model_dump() == before


def test_get_history_normalizes_negative_offset_and_small_limit():
    api_state._state = create_initial_state()
    api_state._state.history_log = [
        HistoryEntry(year=1356, month=i, decree_type="x")
        for i in range(1, 6)
    ]

    result = asyncio.run(routes.get_history(offset=-2, limit=0))
    assert result["offset"] == 0
    assert result["limit"] == 1
    assert len(result["entries"]) == 1
    assert result["entries"][0]["month"] == 1


def test_execute_decree_summary_includes_action_implications_for_commentary():
    api_state._provider = _fake_provider()
    api_state._state = create_initial_state()

    req = routes.DecreeRequest(
        decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)]
    )
    result = asyncio.run(routes.execute_decree(req))

    summary = result["turn_summary"]
    assert summary is not None
    assert summary["action_implications"]
    assert any("严刑峻法" in item for item in summary["action_implications"])
    assert summary["commentary"] == result["narrative"]
    assert result["narrative_status"] in {
        "validated", "repaired", "sanitized", "fallback_facts",
    }
    assert result["narrative_path_id"] == "structured_action"
    assert result["context_version_id"] is not None
    assert result["narrative_request_id"]
    assert result["narrative_progress"][0] == "context_ready"
    assert result["narrative_progress"][-1] == "validated"


def test_execute_decree_wait_turn_includes_memorial_triggers():
    api_state._provider = _fake_provider()
    state = _governance_opening_state()
    state.factions[0].satisfaction = 10
    api_state._state = state

    # Use a valid active script_id for the wait-turn path (no free_text, no decrees)
    active_script = next(
        (e.script_id for e in state.active_events if e.script_id), None
    )
    result = asyncio.run(routes.execute_decree(
        routes.DecreeRequest(source_script_id=active_script)
    ))

    assert "memorial_triggers" in result
    assert len(result["memorial_triggers"]) >= 1


def test_get_state_does_not_generate_or_mutate_placeholder_memorials():
    class _NoMemorialGenerationProvider(FakeProvider):
        def __init__(self):
            self.calls = 0

        async def generate_memorial(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("GET /state must not invoke the provider")

    inner = _NoMemorialGenerationProvider()
    api_state._provider = ResilientProvider(inner, timeout=1, retries=1)
    state = create_initial_state()
    state.memorials.append(Memorial(
        id="mem-read-only",
        author_name="无名吏员",
        author_faction="地方",
        title="待议奏折",
        content="待补充奏疏内容。",
        trigger_reason="测试",
        urgency="中",
        created_year=state.time.year,
        created_month=state.time.month,
    ))
    api_state._state = state
    before = state.model_dump()

    result = asyncio.run(routes.get_state())

    assert inner.calls == 0
    assert result["memorials"][0]["content"] == "待补充奏疏内容。"
    assert api_state._state.model_dump() == before


def test_resolve_memorial_generates_only_after_committed_settlement(monkeypatch, tmp_path):
    class _MemorialNarrativeProvider(FakeProvider):
        async def generate_text_once(self, prompt, **kwargs):
            if "ACTION_INTENT=" in prompt:
                return await super().generate_text_once(prompt, **kwargs)
            return GenerationResult(text="奏折批复已按当前世界事实提交。")

    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "memorial-resolution.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    state = create_initial_state()
    state.memorials.append(Memorial(
        id="mem-resolve",
        author_name="无名吏员",
        author_faction="地方",
        title="请议赈济",
        content="待补充奏疏内容。",
        trigger_reason="灾情",
        urgency="高",
        created_year=state.time.year,
        created_month=state.time.month,
    ))
    api_state._state = state
    api_state._provider = ResilientProvider(
        _MemorialNarrativeProvider(), timeout=1, retries=1,
    )

    result = asyncio.run(routes.resolve_memorial(
        "mem-resolve",
        routes.MemorialResolveRequest(action="rejected"),
    ))

    assert result["narrative"] == "奏折批复已按当前世界事实提交。"
    assert result["narrative_status"] == "validated"
    assert result["narrative_path_id"] == "memorial"
    assert result["settlement_id"] is not None
    assert result["context_version_id"] is not None
    assert result["narrative_artifact_id"] is not None
    assert result["narrative_request_id"]
    assert result["narrative_progress"] == [
        "context_ready", "generating", "validating", "validated",
    ]
    resolved = next(item for item in api_state._state.memorials if item.id == "mem-resolve")
    assert resolved.status == MemorialStatus.REJECTED
    assert resolved.resolution_result is not None
    assert resolved.resolution_result.narrative is None


def test_adopt_suggestion_includes_memorial_triggers():
    api_state._provider = _fake_provider()
    state = _governance_opening_state()
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
    api_state._state = state

    from api.schemas import AdoptSuggestionRequest
    result = asyncio.run(assembly_routes.adopt_suggestion(AdoptSuggestionRequest(suggestion_index=0)))

    assert "memorial_triggers" in result
    assert len(result["memorial_triggers"]) >= 1
    assert result["narrative_path_id"] == "structured_action"
    assert result["context_version_id"] is not None
    assert result["settlement_id"] is not None
    assert result["narrative_request_id"]
    assert result["narrative_progress"][-1] == "validated"


def test_convene_suggestions_persist_only_versioned_safe_factors(monkeypatch, tmp_path):
    class _SuggestionProvider(FakeProvider):
        async def generate_assembly_debate(self, topic, participants, state):
            del topic, state
            return {
                "consensus": "divided",
                "chain_of_thought": "RAW_PRIVATE_REASONING",
                "suggestions": [{
                    "title": "RAW_PROVIDER_TITLE",
                    "description": "RAW_PROVIDER_DESCRIPTION",
                    "decree_type": "disaster_relief",
                    "supporter_names": [participants[0].name, "RAW_UNKNOWN_SUPPORTER"],
                }],
            }

        async def generate_text_once(self, prompt, **kwargs):
            if "ACTION_INTENT=" in prompt:
                return await super().generate_text_once(prompt, **kwargs)
            return GenerationResult(text="朝议已按当前版本事实形成候选方案。")

    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "assembly-suggestion.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    api_state._state = _governance_opening_state()
    api_state._provider = ResilientProvider(_SuggestionProvider(), timeout=1, retries=1)

    result = asyncio.run(assembly_routes.convene_assembly(
        assembly_routes.ConveneAssemblyRequest(
            topic="是否赈济灾区",
            decree_type=DecreeType.DISASTER_RELIEF.value,
        ),
    ))

    suggestion = result["suggestions"][0]
    assert result["narrative_path_id"] == "assembly_debate"
    assert result["context_version_id"] is not None
    assert result["settlement_id"] is not None
    assert result["narrative_artifact_id"] is not None
    assert result["narrative_request_id"]
    assert result["narrative_progress"] == [
        "context_ready", "generating", "validating", "validated",
    ]
    assert suggestion["suggestion_id"]
    assert suggestion["source_game_id"] == api_state._state.world_metadata.game_id
    assert suggestion["source_branch_id"] == api_state._state.world_metadata.branch_id
    assert suggestion["source_version_id"] is not None
    assert suggestion["source_version_id"] != api_state._state.world_metadata.version_id
    assert suggestion["supporter_names"] == [result["participants"][0]["name"]]
    assert {factor["label"] for factor in suggestion["rationale_factors"]} >= {
        "来源版本", "当前议题", "政令类型", "当前在朝支持者",
    }
    serialized = str(result)
    assert "RAW_PRIVATE_REASONING" not in serialized
    assert "RAW_PROVIDER_TITLE" not in serialized
    assert "RAW_PROVIDER_DESCRIPTION" not in serialized
    assert "RAW_UNKNOWN_SUPPORTER" not in serialized


def test_adopt_suggestion_rejects_nonancestor_source_before_effects(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "stale-suggestion.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    current_root = worlds.create_game_with_root(_governance_opening_state())
    foreign_root = worlds.create_game_with_root(_governance_opening_state())
    current = worlds.load_version(current_root.version_id)
    state = current.state.model_copy(deep=True)
    state.last_assembly = CourtAssembly(
        topic="跨世界候选",
        decree_type=DecreeType.DISASTER_RELIEF,
        suggestions=[PolicySuggestion(
            title="错误来源候选",
            description="不得采用",
            related_decree=StructuredDecree(type=DecreeType.DISASTER_RELIEF),
            suggestion_id="foreign-suggestion",
            source_game_id=foreign_root.game_id,
            source_branch_id=foreign_root.branch_id,
            source_version_id=foreign_root.version_id,
        )],
    )
    api_state._publish_world_head(state, current.ref)
    api_state._provider = _fake_provider()
    before = api_state._state.model_dump()

    from api.schemas import AdoptSuggestionRequest
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(assembly_routes.adopt_suggestion(
            AdoptSuggestionRequest(suggestion_index=0),
        ))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "stale_suggestion_source"
    assert api_state._state.model_dump() == before


@pytest.mark.parametrize(
    ("mode", "edited_text", "expected_intent"),
    [
        ("original", None, "朝议方案1"),
        ("edited", "暂缓急征，先清查民户后分区加征", "暂缓急征，先清查民户后分区加征"),
    ],
)
def test_adopt_stale_ancestor_re_evaluates_current_world_before_new_settlement(
    monkeypatch,
    tmp_path,
    mode,
    edited_text,
    expected_intent,
):
    class _CurrentSettlementProvider(FakeProvider):
        def __init__(self):
            super().__init__()
            self.prompts: list[str] = []

        async def generate_text_once(self, prompt, **kwargs):
            self.prompts.append(prompt)
            if "ACTION_INTENT=" in prompt:
                return await super().generate_text_once(prompt, **kwargs)
            return GenerationResult(text="政令已依据当前世界结算执行，旧候选并未预定结果。")

    monkeypatch.setattr(saves, "DB_PATH", tmp_path / f"suggestion-{mode}.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    provider = _CurrentSettlementProvider()
    api_state._provider = ResilientProvider(provider, timeout=1, retries=1)

    root = worlds.create_game_with_root(_governance_opening_state())
    snapshot = worlds.load_version(root.version_id)
    state = snapshot.state.model_copy(deep=True)
    supporter = next(
        entity
        for entity in state.entity_registry.values()
        if entity.entity_type == "person" and entity.status == "active" and entity.available
    )
    suggestion = PolicySuggestion(
        title="朝议方案1",
        description="这是行动建议而非结果承诺；提交后将依据当前世界重新结算。",
        related_decree=StructuredDecree(type=DecreeType.TAX_DECREASE),
        supporter_names=[supporter.display_name],
        suggestion_id="versioned-suggestion",
        source_game_id=snapshot.ref.game_id,
        source_branch_id=snapshot.ref.branch_id,
        source_version_id=snapshot.ref.version_id,
        rationale_factors=assembly_routes._suggestion_rationale(
            state=state,
            topic="是否加征赋税",
            decree_type=DecreeType.TAX_DECREASE,
            supporter_names=[supporter.display_name],
        ),
    )
    state.last_assembly = CourtAssembly(
        topic="是否加征赋税",
        decree_type=DecreeType.TAX_DECREASE,
        suggestions=[suggestion],
    )
    api_state._publish_world_head(state, snapshot.ref)

    changed = state.model_copy(deep=True)
    old_treasury = changed.national_treasury
    changed.national_treasury += 7
    changed = asyncio.run(api_state._set_state(
        changed,
        action_kind="test_world_change",
        raw_text="候选生成后世界发生变化",
    ))
    evaluation_version_id = changed.world_metadata.version_id
    assert evaluation_version_id != suggestion.source_version_id

    from api.schemas import AdoptSuggestionRequest
    result = asyncio.run(assembly_routes.adopt_suggestion(AdoptSuggestionRequest(
        mode=mode,
        suggestion_index=0,
        suggestion_id=suggestion.suggestion_id,
        source_version_id=suggestion.source_version_id,
        edited_text=edited_text,
    )))

    assert result["suggestion_adoption_mode"] == mode
    assert result["suggestion_was_stale"] is True
    assert result["suggestion_source_version_id"] == str(suggestion.source_version_id)
    assert result["suggestion_evaluation_version_id"] == str(evaluation_version_id)
    assert result["settlement_id"] is not None
    assert result["context_version_id"] != str(suggestion.source_version_id)
    assert result["narrative"] == "政令已依据当前世界结算执行，旧候选并未预定结果。"
    assert expected_intent in "\n".join(provider.prompts)
    current_factors = result["suggestion_rationale_factors"]
    assert next(f for f in current_factors if f["label"] == "来源版本")["value"] == str(evaluation_version_id)
    assert next(f for f in current_factors if f["label"] == "当前国库")["value"] == str(old_treasury + 7)


def test_adopt_free_input_uses_canonical_freeform_settlement(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "suggestion-free-input.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    api_state._state = _governance_opening_state()
    api_state._provider = _fake_provider()

    from api.schemas import AdoptSuggestionRequest
    result = asyncio.run(assembly_routes.adopt_suggestion(AdoptSuggestionRequest(
        mode="free_input",
        free_text="加征商税，先补充军饷",
    )))

    assert result["suggestion_adoption_mode"] == "free_input"
    assert result["suggestion_id"] is None
    assert result["narrative_path_id"] == "freeform_action"
    assert result["settlement_id"] is not None
    assert result["context_version_id"] is not None
    assert result["suggestion_rationale_factors"] == []


def test_assembly_debate_discards_raw_speeches_and_returns_postcommit_artifact(
    monkeypatch,
    tmp_path,
):
    class _AssemblyProvider(FakeProvider):
        async def generate_debate_speeches(self, topic, ministers, state):
            del topic, state
            return [
                {
                    "minister_name": minister.name,
                    "faction": "RAW_FACTION_OVERRIDE",
                    "content": f"RAW_ASSEMBLY_{index}",
                    "stance": "赞成" if index == 0 else "反对",
                }
                for index, minister in enumerate(ministers)
            ]

        async def generate_text_once(self, prompt, **kwargs):
            if "ACTION_INTENT=" in prompt:
                return await super().generate_text_once(prompt, **kwargs)
            return GenerationResult(text="朝臣立场已按当前在朝名单汇总，裁断仍归主公。")

    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "assembly-debate.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    state = _governance_opening_state()
    active = [item for item in state.ministers if item.status == MinisterStatus.ACTIVE][:3]
    assert len(active) >= 3
    state.last_assembly = CourtAssembly(
        phase=AssemblyPhase.PETITION,
        participants=[
            AssemblyParticipant(
                name=item.name,
                faction=item.faction,
                position=item.positions[0] if item.positions else "朝臣",
                argument_text="",
            )
            for item in active
        ],
    )
    api_state._state = state
    api_state._provider = ResilientProvider(_AssemblyProvider(), timeout=1, retries=1)

    result = asyncio.run(assembly_routes.assembly_debate(
        assembly_routes.AssemblyDebateRequest(topic="是否整饬军纪"),
    ))

    assert result["debate_text"] == "朝臣立场已按当前在朝名单汇总，裁断仍归主公。"
    assert "RAW_ASSEMBLY" not in str(result)
    assert result["narrative_status"] == "validated"
    assert result["narrative_path_id"] == "assembly_debate"
    assert result["settlement_id"] is not None
    assert result["context_version_id"] is not None
    assert result["narrative_artifact_id"] is not None
    assert result["narrative_request_id"]
    assert result["narrative_progress"] == [
        "context_ready", "generating", "validating", "validated",
    ]
    assert len(result["suggestions"]) == 1
    assert result["suggestions"][0]["suggestion_id"]
    assert result["suggestions"][0]["source_version_id"] is not None
    assert "结果承诺" in result["suggestions"][0]["description"]
    assert api_state._state.last_assembly.debate_text == ""
    assert all(speech.content == "" for speech in api_state._state.last_assembly.speeches)
    assert [speech.faction for speech in api_state._state.last_assembly.speeches] == [
        item.faction for item in active
    ]


def test_legacy_debate_start_returns_canonical_text_only(monkeypatch, tmp_path):
    class _LegacyDebateProvider(FakeProvider):
        async def generate_debate_narrative(self, topic, minister_a, minister_b, state):
            del topic, state
            return DebateResult(
                debate_text="RAW_LEGACY_DEBATE",
                minister_a=DebateMinister(
                    name=minister_a.name,
                    faction=minister_a.faction,
                    position_summary="RAW_POSITION_A",
                ),
                minister_b=DebateMinister(
                    name=minister_b.name,
                    faction=minister_b.faction,
                    position_summary="RAW_POSITION_B",
                ),
                option_a=StructuredDecree(type=DecreeType.TAX_INCREASE),
                option_b=StructuredDecree(type=DecreeType.TAX_DECREASE),
                keywords=["RAW_KEYWORD"],
            )

        async def generate_text_once(self, prompt, **kwargs):
            if "ACTION_INTENT=" in prompt:
                return await super().generate_text_once(prompt, **kwargs)
            return GenerationResult(text="两位参议者的结构化方案已提交，仍待主公裁断。")

    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "legacy-debate.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    api_state._state = _governance_opening_state()
    api_state._provider = ResilientProvider(_LegacyDebateProvider(), timeout=1, retries=1)
    category = DecreeType.TAX_INCREASE.value
    topic = routes.DEBATE_TOPICS[category][0]["topic"]

    result = asyncio.run(routes.start_debate(
        routes.DebateStartRequest(category=category, topic=topic),
    ))

    assert result["debate_text"] == "两位参议者的结构化方案已提交，仍待主公裁断。"
    assert "RAW_" not in str(result)
    assert result["minister_a"]["position_summary"] == "提出结构化方案甲"
    assert result["minister_b"]["position_summary"] == "提出结构化方案乙"
    assert result["narrative_status"] == "validated"
    assert result["narrative_path_id"] == "assembly_debate"
    assert result["settlement_id"] is not None
    assert result["context_version_id"] is not None
    assert result["narrative_artifact_id"] is not None
    assert result["narrative_request_id"]
    assert result["narrative_progress"] == [
        "context_ready", "generating", "validating", "validated",
    ]


def test_split_stream_sentences_preserves_sentence_boundaries():
    from api.state import _split_stream_sentences
    text = "朕已知晓。即刻施行！\n再议后续；"
    result = _split_stream_sentences(text)
    assert result == ["朕已知晓。", "即刻施行！", "再议后续；"]


def test_execute_decree_stream_emits_final_event():
    api_state._provider = _fake_provider()
    api_state._state = create_initial_state()

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


def test_execute_decree_stream_buffers_provider_tokens_until_validation():
    class _TokenStreamFakeProvider(FakeProvider):
        async def generate_text_once(self, prompt, **kw):
            if "ACTION_INTENT=" in prompt:
                return await super().generate_text_once(prompt, **kw)
            return GenerationResult(text="甲乙")

        async def stream_narrative(self, *a, **kw):
            raise AssertionError("legacy provider stream must not be called")

    api_state._provider = ResilientProvider(_TokenStreamFakeProvider(), timeout=1, retries=1)
    api_state._state = create_initial_state()

    req = routes.DecreeRequest(decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)])
    stream_response = asyncio.run(routes.execute_decree_stream(req))

    async def _collect_stream():
        parts: list[str] = []
        async for chunk in stream_response.body_iterator:
            parts.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
        return "".join(parts)

    payload = asyncio.run(_collect_stream())
    assert payload.count("event: narrative") == 1
    assert "\"stage\": \"validated\"" in payload
    assert "\"chunk\": \"甲乙\"" in payload


def test_execute_decree_stream_never_exposes_invalid_candidate_before_repair():
    class _InvalidThenRepairProvider(FakeProvider):
        async def generate_text_once(self, prompt, **kw):
            if "ACTION_INTENT=" in prompt:
                return await super().generate_text_once(prompt, **kw)
            text = (
                "朝廷已按当前状态执行政令。"
                if "REPAIR_REQUIREMENTS=" in prompt
                else "徐达：臣仍在主持军务。"
            )
            return GenerationResult(text=text)

        async def stream_narrative(self, *a, **kw):
            raise AssertionError("legacy provider stream must not be called")

    api_state._provider = ResilientProvider(_InvalidThenRepairProvider(), timeout=1, retries=1)
    state = create_initial_state()
    minister = next(item for item in state.ministers if item.name == "徐达")
    minister.status = MinisterStatus.REMOVED
    api_state._state = state

    req = routes.DecreeRequest(
        decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)],
    )
    stream_response = asyncio.run(routes.execute_decree_stream(req))

    async def _collect_stream():
        parts: list[str] = []
        async for chunk in stream_response.body_iterator:
            parts.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
        return "".join(parts)

    payload = asyncio.run(_collect_stream())
    assert "臣仍在主持军务" not in payload
    assert "\"chunk\": \"徐达" not in payload
    assert "朝廷已按当前状态执行政令。" in payload
    assert payload.index("\"stage\": \"validated\"") < payload.index("event: narrative")


def test_execute_decree_stream_emits_fallback_narrative_chunk():
    class _EmptyStreamFakeProvider(FakeProvider):
        async def generate_text_once(self, prompt, **kw):
            if "ACTION_INTENT=" in prompt:
                return await super().generate_text_once(prompt, **kw)
            return GenerationResult(text="整段叙事")

        async def stream_narrative(self, *a, **kw):
            raise AssertionError("legacy provider stream must not be called")

    api_state._provider = ResilientProvider(_EmptyStreamFakeProvider(), timeout=1, retries=1)
    api_state._state = create_initial_state()

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


def test_update_ai_settings_schema_requires_verification_token():
    from pydantic import ValidationError
    from api.schemas import AISettingsApplyRequest

    with pytest.raises(ValidationError):
        AISettingsApplyRequest(
            provider="openai",
            api_key="sk-test",
            model="main-model",
            verification_token="",
        )


def test_ai_config_requires_api_key_before_probe_or_apply():
    from ai.config import AIConfigurationError, normalize_ai_config

    with pytest.raises(AIConfigurationError) as exc_info:
        normalize_ai_config(
            provider="openai",
            api_key="",
            model="main-model",
            base_url="https://api.example.com/v1",
        )
    assert exc_info.value.error_code == "missing_api_key"


def test_update_ai_settings_normalizes_openai_chat_completions_base_url():
    from ai.config import normalize_ai_config

    result = normalize_ai_config(
        provider="openai",
        provider_type="openai",
        api_key="sk-test",
        base_url="https://example.com/v1/chat/completions",
        model="deepseek-v4-pro",
    )

    assert result.base_url == "https://example.com/v1"


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

    async def resolver(_host, _port):
        return ["93.184.216.34"]

    from api.ai_settings_service import AISettingsService

    service = AISettingsService(
        environment={},
        resolver=resolver,
        assessment_loader=lambda _fingerprint: None,
        assessment_saver=lambda _fingerprint, _report: None,
    )
    monkeypatch.setattr(settings_routes, "get_ai_settings_service", lambda: service)
    monkeypatch.setattr(
        "api.ai_settings_service.create_safe_async_client",
        lambda *args, **kwargs: _FakeClient(),
    )

    from api.schemas import AIModelListRequest
    req = AIModelListRequest(
        provider="openai",
        api_key="sk-test",
        base_url="https://example.com/v1",
    )

    result = asyncio.run(settings_routes.list_ai_models(req))

    assert result["provider"] == "openai"
    assert result["source"] == "openai-compatible"
    assert result["models"] == ["model-a", "model-b"]


def test_get_ai_settings_masks_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL_NAME", "main-model")

    result = asyncio.run(settings_routes.get_ai_settings("openai"))

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

    async def resolver(_host, _port):
        return ["93.184.216.34"]

    from api.ai_settings_service import AISettingsService

    service = AISettingsService(
        environment={"AI_PROVIDER": "openai", "OPENAI_API_KEY": "sk-real"},
        resolver=resolver,
        assessment_loader=lambda _fingerprint: None,
        assessment_saver=lambda _fingerprint, _report: None,
    )
    monkeypatch.setattr(settings_routes, "get_ai_settings_service", lambda: service)
    monkeypatch.setattr(
        "api.ai_settings_service.create_safe_async_client",
        lambda *args, **kwargs: _FakeClient(),
    )

    from api.schemas import AIModelListRequest
    req = AIModelListRequest(
        provider="openai",
        api_key="********",
        base_url="https://example.com/v1",
    )

    result = asyncio.run(settings_routes.list_ai_models(req))

    assert result["models"] == ["model-a"]
    assert captured_headers.get("Authorization") == "Bearer sk-real"


def test_list_ai_models_rejects_private_base_url_by_default():
    from api.schemas import AIModelListRequest
    req = AIModelListRequest(
        provider="openai",
        api_key="sk-test",
        base_url="http://127.0.0.1:8000/v1",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(settings_routes.list_ai_models(req))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "invalid_base_url"


# ── 10.3 FREEFORM_EMPTY error when source_script_id present ──

def test_freeform_empty_returns_error_with_script_id():
    class _EmptyFreeformMock(FakeProvider):
        async def process_freeform(self, text, game_state, *, script_context=None):
            return FreeformResult(
                effects={}, narrative="", rationale="",
                reactions=[], new_events=[],
            )

    api_state._provider = ResilientProvider(_EmptyFreeformMock(), timeout=1, retries=1)
    state = _governance_opening_state()
    api_state._state = state

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


def test_minister_dialogue_returns_503_when_ai_fails(monkeypatch):
    class _FailDialogueProvider(FakeProvider):
        async def generate_minister_dialogue(self, *args, **kwargs):
            raise RuntimeError("dialogue failed")

    monkeypatch.setenv("AI_PROVIDER", "openai")
    api_state._provider = ResilientProvider(_FailDialogueProvider(), timeout=1, retries=1)
    api_state._state = _governance_opening_state()

    minister_name = next(m.name for m in api_state._state.ministers if m.status.value == "active")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            routes.minister_dialogue(
                minister_name=minister_name,
                req=routes.DialogueRequest(message="测试问话"),
            )
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error_code"] == "dialogue_generation_failed"


def test_minister_dialogue_uses_person_scoped_postcommit_narrative(monkeypatch, tmp_path):
    class _DialogueProvider(FakeProvider):
        async def generate_minister_dialogue(self, *args, **kwargs):
            return {
                "reply": "RAW_DIALOGUE_CANDIDATE",
                "loyalty_change": 2,
                "mood": "support",
            }

        async def generate_text_once(self, prompt, **kwargs):
            if "ACTION_INTENT=" in prompt:
                return await super().generate_text_once(prompt, **kwargs)
            return GenerationResult(text="臣已依当前事实回应，后续仍待主公裁断。")

    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "dialogue.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    api_state._provider = ResilientProvider(_DialogueProvider(), timeout=1, retries=1)
    api_state._state = _governance_opening_state()
    minister = next(item for item in api_state._state.ministers if item.status == MinisterStatus.ACTIVE)
    loyalty_before = minister.loyalty

    result = asyncio.run(routes.minister_dialogue(
        minister.name,
        routes.DialogueRequest(message="可愿继续辅政？"),
    ))

    assert result["reply"] == "臣已依当前事实回应，后续仍待主公裁断。"
    assert "RAW_DIALOGUE_CANDIDATE" not in str(result)
    assert result["loyalty_change"] == 2
    assert result["narrative_status"] == "validated"
    assert result["narrative_path_id"] == "entity_dialogue"
    assert result["settlement_id"] is not None
    assert result["context_version_id"] is not None
    assert result["narrative_artifact_id"] is not None
    assert result["narrative_request_id"]
    assert result["narrative_progress"] == [
        "context_ready", "generating", "validating", "validated",
    ]
    committed_minister = next(
        item for item in api_state._state.ministers if item.name == minister.name
    )
    assert committed_minister.loyalty == loyalty_before + 2
    assert api_state._state.minister_conversations.get(minister.name, []) == []

    person = next(
        item for item in api_state._state.entity_registry.values()
        if item.entity_type == "person" and item.display_name == minister.name
    )
    ref = api_state._get_world_head_ref()
    memories = narrative_memory.list_visible_memories(
        game_id=ref.game_id,
        branch_id=ref.branch_id,
        version_id=ref.version_id,
        mode="dialogue",
        topic_id=f"dialogue:{minister.name}:default",
        person_entity_id=person.entity_id,
        current_phase=api_state._state.phase,
        current_chapter=api_state._state.chapter,
    )
    assert [(item.role, item.content) for item in memories] == [
        ("user", "可愿继续辅政？"),
        ("assistant", "臣已依当前事实回应，后续仍待主公裁断。"),
    ]


def test_dynamic_dialogue_actor_uses_registry_capability_and_ended_actor_is_rejected(
    monkeypatch,
    tmp_path,
):
    from models.world import (
        ENTITY_DIALOGUE_CAPABILITY,
        EntitySource,
        PermissionReference,
        PersonEntity,
        new_entity_id,
        new_permission_id,
    )

    class _DynamicDialogueProvider(FakeProvider):
        seen_actor = None

        async def generate_minister_dialogue(self, minister, *args, **kwargs):
            self.seen_actor = minister.name
            return {
                "reply": "RAW_DYNAMIC_DIALOGUE",
                "loyalty_change": 3,
                "mood": "support",
            }

        async def generate_text_once(self, prompt, **kwargs):
            if "ACTION_INTENT=" in prompt:
                return await super().generate_text_once(prompt, **kwargs)
            return GenerationResult(text="新任参议依当前世界事实作答，仍可继续共商后路。")

    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "dynamic-dialogue.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    state = _governance_opening_state()
    source = EntitySource(kind="adjudication", summary="当前分支推举的新人物")
    active_id = new_entity_id()
    ended_id = new_entity_id()
    state.entity_registry = {
        active_id: PersonEntity(
            entity_id=active_id,
            display_name="新任参议",
            roles=["参议"],
            source=source,
            permissions=[PermissionReference(
                permission_id=new_permission_id(),
                capability=ENTITY_DIALOGUE_CAPABILITY,
            )],
        ),
        ended_id: PersonEntity(
            entity_id=ended_id,
            display_name="已故旧臣",
            status="ended",
            available=False,
            source=source,
            permissions=[PermissionReference(
                permission_id=new_permission_id(),
                capability=ENTITY_DIALOGUE_CAPABILITY,
            )],
        ),
    }
    provider = _DynamicDialogueProvider()
    api_state._provider = ResilientProvider(provider, timeout=1, retries=1)
    api_state._state = state

    result = asyncio.run(routes.minister_dialogue(
        str(active_id),
        routes.DialogueRequest(message="请陈述当前方略。"),
    ))

    assert provider.seen_actor == "新任参议"
    assert result["reply"] == "新任参议依当前世界事实作答，仍可继续共商后路。"
    assert result["loyalty_change"] == 0
    assert result["narrative_path_id"] == "entity_dialogue"
    assert str(active_id) in {
        str(entity_id) for entity_id in result["state"]["entity_registry"]
    }

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.minister_dialogue(
            str(ended_id),
            routes.DialogueRequest(message="旧臣可还在？"),
        ))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error_code"] == "entity_not_available"


# ── 10.10 200-char limit boundary test ──

def test_200_char_limit_accepted():
    api_state._provider = _fake_provider()
    api_state._state = create_initial_state()

    text_200 = "字" * 200
    # Should not raise INPUT_TOO_LONG (may raise other errors like FREEFORM_EMPTY)
    try:
        asyncio.run(routes.execute_decree(
            routes.DecreeRequest(free_text=text_200)
        ))
    except HTTPException as e:
        assert e.detail.get("error_code") != "INPUT_TOO_LONG"


def test_201_char_limit_rejected():
    api_state._provider = _fake_provider()
    api_state._state = create_initial_state()

    text_201 = "字" * 201
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(
            routes.DecreeRequest(free_text=text_201)
        ))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error_code"] == "INPUT_TOO_LONG"


# ── 10.11 source_script_id validation tests ──

def test_invalid_script_id_rejected():
    api_state._provider = _fake_provider()
    api_state._state = create_initial_state()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(
            routes.DecreeRequest(source_script_id="nonexistent-script")
        ))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "INVALID_SCRIPT_ID"


def test_script_already_resolved_rejected():
    api_state._provider = _fake_provider()
    state = _governance_opening_state()
    active_script = next(
        (e.script_id for e in state.active_events if e.script_id), None
    )
    assert active_script is not None
    state.resolved_script_ids.add(active_script)
    api_state._state = state

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(
            routes.DecreeRequest(source_script_id=active_script, free_text="test")
        ))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "SCRIPT_ALREADY_RESOLVED"


def test_script_not_active_rejected():
    api_state._provider = _fake_provider()
    state = create_initial_state()
    # Use a valid script ID from registry that's NOT in active_events
    from engine.scripts import SCRIPT_REGISTRY
    non_active_id = next(
        sid for sid in SCRIPT_REGISTRY
        if sid not in {e.script_id for e in state.active_events}
    )
    api_state._state = state

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(
            routes.DecreeRequest(source_script_id=non_active_id, free_text="test")
        ))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "SCRIPT_NOT_ACTIVE"
