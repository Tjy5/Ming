"""Versioned registry for every player-visible AI narrative path.

The registry is deliberately static.  A player-visible path is a release
contract, not something inferred from whichever routers happened to import in a
particular process.  Tests compare the required manifest with these production
registrations so a missing/duplicate path fails closed.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


NARRATIVE_REGISTRY_VERSION = "narrative-paths-v1"

NarrativePathId = Literal[
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
]

REQUIRED_NARRATIVE_PATH_IDS: frozenset[NarrativePathId] = frozenset(
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


class NarrativePathDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_version: Literal["narrative-paths-v1"] = NARRATIVE_REGISTRY_VERSION
    path_id: NarrativePathId
    endpoint: str = Field(min_length=1)
    owner_module: str = Field(min_length=1)
    owner_function: str = Field(min_length=1)
    required_context_sections: tuple[str, ...] = Field(min_length=1)
    memory_mode: str = Field(min_length=1)
    person_scoped: bool = False
    topic_scoped: bool = True
    output_contract: Literal["text", "structured_text"] = "text"
    validator_policy: Literal["strict_facts", "strict_facts_and_topic"] = (
        "strict_facts_and_topic"
    )
    repair_allowed: bool = True
    settlement_required: bool = False
    fallback_source: Literal["settlement_facts", "safe_context_summary"]
    stream_policy: Literal["not_streamed", "validated_sentence_chunks"] = "not_streamed"

    @model_validator(mode="after")
    def _validate_stream_contract(self) -> "NarrativePathDefinition":
        if self.path_id.endswith("_sse") and self.stream_policy != "validated_sentence_chunks":
            raise ValueError("SSE narrative paths must use validated sentence chunks")
        if len(set(self.required_context_sections)) != len(self.required_context_sections):
            raise ValueError("required context sections must be unique")
        return self


_COMMON_CONTEXT = (
    "identity",
    "time_calendar_activity",
    "player_identity_freedom_goal",
    "current_action",
    "entities_relationships_permissions_knowledge",
    "regions_events_policies_commitments",
    "world_state_metrics_modifiers",
    "executor_and_roll",
    "memory_lineage_scope",
)
_SETTLEMENT_CONTEXT = (*_COMMON_CONTEXT, "settlement_facts")


def _definition(
    path_id: NarrativePathId,
    endpoint: str,
    owner_module: str,
    owner_function: str,
    *,
    memory_mode: str,
    settlement_required: bool = False,
    person_scoped: bool = False,
    output_contract: Literal["text", "structured_text"] = "text",
    validator_policy: Literal["strict_facts", "strict_facts_and_topic"] = (
        "strict_facts_and_topic"
    ),
    repair_allowed: bool = True,
    fallback_source: Literal["settlement_facts", "safe_context_summary"] | None = None,
    stream_policy: Literal["not_streamed", "validated_sentence_chunks"] = "not_streamed",
) -> NarrativePathDefinition:
    return NarrativePathDefinition(
        path_id=path_id,
        endpoint=endpoint,
        owner_module=owner_module,
        owner_function=owner_function,
        required_context_sections=(
            _SETTLEMENT_CONTEXT if settlement_required else _COMMON_CONTEXT
        ),
        memory_mode=memory_mode,
        person_scoped=person_scoped,
        output_contract=output_contract,
        validator_policy=validator_policy,
        repair_allowed=repair_allowed,
        settlement_required=settlement_required,
        fallback_source=(
            fallback_source
            or ("settlement_facts" if settlement_required else "safe_context_summary")
        ),
        stream_policy=stream_policy,
    )


_DEFINITIONS = (
    _definition(
        "unified_action", "/api/actions", "api.action_routes", "execute_action",
        memory_mode="world_action", settlement_required=True,
    ),
    _definition(
        "trpg_gm_action", "/api/trpg/act", "api.trpg", "act",
        memory_mode="trpg", settlement_required=True, output_contract="structured_text",
    ),
    _definition(
        "assembly_debate", "/api/assembly/debate", "api.assembly_routes", "assembly_debate",
        memory_mode="assembly", settlement_required=True, output_contract="structured_text",
    ),
    _definition(
        "memorial", "/api/memorial/{memorial_id}/resolve", "api.routes", "resolve_memorial",
        memory_mode="governance", settlement_required=True,
        output_contract="structured_text",
    ),
    _definition(
        "entity_dialogue", "/api/minister/{minister_name}/dialogue", "api.routes",
        "minister_dialogue", memory_mode="dialogue", person_scoped=True,
        settlement_required=True, output_contract="structured_text",
    ),
    _definition(
        "freeform_action", "/api/decree", "api.routes", "execute_decree",
        memory_mode="governance", settlement_required=True,
    ),
    _definition(
        "structured_action", "/api/decree", "api.routes", "execute_decree",
        memory_mode="governance", settlement_required=True,
    ),
    _definition(
        "monthly_review", "/api/advance-month", "api.routes", "advance_month_endpoint",
        memory_mode="governance", settlement_required=True,
    ),
    _definition(
        "ordinary_chat", "/api/chat", "api.chat_routes", "chat_stream",
        memory_mode="chat",
    ),
    _definition(
        "decree_sse", "/api/decree/stream", "api.routes", "execute_decree_stream",
        memory_mode="governance", settlement_required=True,
        stream_policy="validated_sentence_chunks",
    ),
    _definition(
        "chat_sse", "/api/chat", "api.chat_routes", "chat_stream",
        memory_mode="chat", stream_policy="validated_sentence_chunks",
    ),
)


def _build_registry(
    definitions: tuple[NarrativePathDefinition, ...],
) -> MappingProxyType[NarrativePathId, NarrativePathDefinition]:
    registry: dict[NarrativePathId, NarrativePathDefinition] = {}
    owners: set[tuple[str, str, str]] = set()
    for definition in definitions:
        if definition.path_id in registry:
            raise ValueError(f"duplicate narrative path id: {definition.path_id}")
        owner_key = (
            definition.endpoint,
            definition.owner_module,
            definition.owner_function,
        )
        # One endpoint/function may intentionally expose multiple semantic paths
        # (for example structured and freeform decrees), but the full path ID is
        # still unique.  Track exact duplicates only.
        exact_key = (*owner_key, definition.path_id)
        if exact_key in owners:
            raise ValueError(f"duplicate narrative path owner: {exact_key}")
        owners.add(exact_key)
        registry[definition.path_id] = definition
    missing = REQUIRED_NARRATIVE_PATH_IDS - registry.keys()
    extra = registry.keys() - REQUIRED_NARRATIVE_PATH_IDS
    if missing or extra:
        raise ValueError(
            f"narrative registry mismatch: missing={sorted(missing)} extra={sorted(extra)}",
        )
    return MappingProxyType(registry)


NARRATIVE_PATHS = _build_registry(_DEFINITIONS)


def get_narrative_path(path_id: NarrativePathId) -> NarrativePathDefinition:
    return NARRATIVE_PATHS[path_id]


def iter_narrative_paths() -> tuple[NarrativePathDefinition, ...]:
    return tuple(NARRATIVE_PATHS[path_id] for path_id in sorted(NARRATIVE_PATHS))


def resolve_narrative_owner(definition: NarrativePathDefinition) -> Callable[..., object]:
    """Resolve a registered production owner lazily to avoid import cycles."""

    module = importlib.import_module(definition.owner_module)
    owner = getattr(module, definition.owner_function, None)
    if not callable(owner):
        raise ValueError(
            "narrative owner is not callable: "
            f"{definition.owner_module}.{definition.owner_function}",
        )
    return owner
