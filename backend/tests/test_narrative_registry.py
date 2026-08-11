from __future__ import annotations

import pytest

from ai.narrative_registry import (
    NARRATIVE_PATHS,
    REQUIRED_NARRATIVE_PATH_IDS,
    NarrativePathDefinition,
    _build_registry,
    iter_narrative_paths,
    resolve_narrative_owner,
)


EXPECTED_REQUIRED_PATHS = frozenset(
    {
        "unified_action",
        "trpg_gm_action",
        "assembly_debate",
        "memorial",
        "entity_dialogue",
        "freeform_action",
        "structured_action",
        "monthly_review",
        "ordinary_chat",
        "decree_sse",
        "chat_sse",
    },
)


def test_required_narrative_paths_are_all_registered_once():
    assert REQUIRED_NARRATIVE_PATH_IDS == EXPECTED_REQUIRED_PATHS
    assert frozenset(NARRATIVE_PATHS) == REQUIRED_NARRATIVE_PATH_IDS
    assert len(iter_narrative_paths()) == len(REQUIRED_NARRATIVE_PATH_IDS)
    assert all(definition.owner_function for definition in iter_narrative_paths())
    assert all(definition.required_context_sections for definition in iter_narrative_paths())


def test_registered_owners_are_real_fastapi_production_routes():
    from main import app

    production_routes = {
        (route.path, route.endpoint.__module__, route.endpoint.__name__)
        for route in app.routes
        if getattr(route, "endpoint", None) is not None
    }
    for definition in iter_narrative_paths():
        owner = resolve_narrative_owner(definition)
        assert owner.__module__ == definition.owner_module
        assert owner.__name__ == definition.owner_function
        assert (
            definition.endpoint,
            definition.owner_module,
            definition.owner_function,
        ) in production_routes


def test_required_context_contract_is_field_complete_and_explicit():
    common = {
        "identity",
        "time_calendar_activity",
        "player_identity_freedom_goal",
        "current_action",
        "entities_relationships_permissions_knowledge",
        "regions_events_policies_commitments",
        "world_state_metrics_modifiers",
        "executor_and_roll",
        "memory_lineage_scope",
    }
    for definition in iter_narrative_paths():
        assert common <= set(definition.required_context_sections)
        assert ("settlement_facts" in definition.required_context_sections) is (
            definition.settlement_required
        )
        assert definition.fallback_source == (
            "settlement_facts" if definition.settlement_required else "safe_context_summary"
        )


def test_every_sse_path_buffers_until_validated_sentence_chunks():
    streamed = [
        definition
        for definition in iter_narrative_paths()
        if definition.path_id.endswith("_sse")
    ]
    assert streamed
    assert all(
        definition.stream_policy == "validated_sentence_chunks"
        for definition in streamed
    )


def test_registry_rejects_duplicate_or_missing_required_path():
    definitions = iter_narrative_paths()
    with pytest.raises(ValueError, match="duplicate narrative path id"):
        _build_registry((*definitions, definitions[0]))
    with pytest.raises(ValueError, match="registry mismatch"):
        _build_registry(definitions[:-1])


def test_sse_definition_cannot_claim_raw_or_nonstreamed_delivery():
    with pytest.raises(ValueError, match="validated sentence chunks"):
        NarrativePathDefinition(
            path_id="chat_sse",
            endpoint="/api/chat",
            owner_module="api.chat_routes",
            owner_function="chat_stream",
            required_context_sections=("identity",),
            memory_mode="chat",
            fallback_source="safe_context_summary",
            stream_policy="not_streamed",
        )
