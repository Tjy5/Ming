"""Deterministic empty-roster continuity: vacuum detection and succession derivation.

When every governance-capable registry actor is gone the world must not stall.
This module derives replacement actors from current world facts (player faction,
regions, existing registry) as a pure proposal. It performs no AI call and no
state write; the proposal is validated and committed through the same settlement
pipeline as any adjudicated action.
"""

from __future__ import annotations

import hashlib

from engine.entity_views import assembly_actor_views
from models.game import GameState
from models.settlement import (
    AdjudicationProposal,
    EntityWorldDelta,
    ProviderAttribution,
    RelationshipWorldDelta,
    WorldDelta,
)
from models.world import (
    ASSEMBLY_PARTICIPATE_CAPABILITY,
    ENTITY_DIALOGUE_CAPABILITY,
    MEMORIAL_SUBMIT_CAPABILITY,
    OFFICE_APPOINTABLE_CAPABILITY,
    Duration,
    EntitySource,
    FactionEntity,
    PermissionReference,
    PersonEntity,
    RegionEntity,
    SettlementId,
    TemporaryAuthorityEntity,
    VersionId,
    new_delta_id,
    new_entity_id,
    new_permission_id,
)


GOVERNANCE_CONTINUITY_ACTION_KIND = "system_continuity"
_CONTINUITY_SOURCE = "system-continuity:governance-vacuum"

# Fictional-only pools; historical canon is never used to name derived actors.
_SUCCESSION_SURNAMES = (
    "沈", "顾", "陆", "周", "吴", "郑", "王", "张", "刘", "陈", "赵", "孙",
)
_SUCCESSION_GIVEN_NAMES = (
    "承业", "维宁", "定远", "怀德", "守诚", "启民",
    "安世", "秉文", "立本", "弘毅", "思齐", "观澜",
)

_PERSON_CAPABILITIES = (
    ASSEMBLY_PARTICIPATE_CAPABILITY,
    ENTITY_DIALOGUE_CAPABILITY,
    MEMORIAL_SUBMIT_CAPABILITY,
    OFFICE_APPOINTABLE_CAPABILITY,
)
_AUTHORITY_CAPABILITIES = (
    ASSEMBLY_PARTICIPATE_CAPABILITY,
    MEMORIAL_SUBMIT_CAPABILITY,
)


def detect_governance_vacuum(state: GameState) -> bool:
    """True when a versioned registry world has no assembly-capable actor.

    Pre-root legacy states (empty registry) keep their legacy fallback and are
    not treated as a vacuum; continuity only applies to committed world graphs.
    """

    if not state.entity_registry:
        return False
    return not assembly_actor_views(state)


def _anchor_faction(state: GameState) -> FactionEntity | None:
    controlled_id = state.player_world_status.controlled_faction_id
    if controlled_id is not None:
        controlled = state.entity_registry.get(controlled_id)
        if isinstance(controlled, FactionEntity) and controlled.status != "ended":
            return controlled
    factions = [
        entity
        for entity in state.entity_registry.values()
        if isinstance(entity, FactionEntity) and entity.status == "active"
    ]
    if not factions:
        return None
    return max(
        factions,
        key=lambda faction: (
            len(faction.member_ids),
            faction.influence or 0,
            faction.display_name,
        ),
    )


def _anchor_region(
    state: GameState,
    faction: FactionEntity | None,
) -> RegionEntity | None:
    regions = [
        entity
        for entity in state.entity_registry.values()
        if isinstance(entity, RegionEntity) and entity.status == "active"
    ]
    if not regions:
        return None
    if faction is not None:
        controlled = [
            region
            for region in regions
            if region.controller_entity_id == faction.entity_id
        ]
        if controlled:
            return sorted(controlled, key=lambda region: region.display_name)[0]
    return sorted(regions, key=lambda region: region.display_name)[0]


def _succession_name(state: GameState) -> str:
    """Pick a unique fictional name deterministically from the current registry."""

    digest = int(
        hashlib.sha256(
            "|".join(sorted(str(entity_id) for entity_id in state.entity_registry)).encode(
                "utf-8",
            ),
        ).hexdigest(),
        16,
    )
    existing = {entity.display_name for entity in state.entity_registry.values()}
    attempts = len(_SUCCESSION_SURNAMES) * len(_SUCCESSION_GIVEN_NAMES)
    for attempt in range(attempts):
        surname = _SUCCESSION_SURNAMES[(digest + attempt) % len(_SUCCESSION_SURNAMES)]
        given = _SUCCESSION_GIVEN_NAMES[
            (digest // len(_SUCCESSION_SURNAMES) + attempt) % len(_SUCCESSION_GIVEN_NAMES)
        ]
        candidate = f"{surname}{given}"
        if candidate not in existing:
            return candidate
    return f"推举义士{digest % 997}"


def _permissions(capabilities: tuple[str, ...]) -> list[PermissionReference]:
    return [
        PermissionReference(
            permission_id=new_permission_id(),
            capability=capability,
        )
        for capability in capabilities
    ]


def build_continuity_proposal(
    state: GameState,
    *,
    settlement_id: SettlementId,
    version_id: VersionId,
) -> AdjudicationProposal:
    """Derive one person plus one non-person replacement body from world facts.

    Both entities carry stable ids, source provenance, permissions and a
    first-appearance reference to the continuity settlement, so narrative, UI,
    policy and save/load consumers can trace why the world continued this way.
    """

    faction = _anchor_faction(state)
    region = _anchor_region(state, faction)
    person_id = new_entity_id()
    authority_id = new_entity_id()
    person_name = _succession_name(state)

    anchor_facts: list[str] = []
    if faction is not None:
        anchor_facts.append(f"权力来源：{faction.display_name}")
    if region is not None:
        anchor_facts.append(f"立足地区：{region.display_name}")
    if not anchor_facts:
        anchor_facts.append("无可用派系与地区锚点，由行在军民共同推举")

    date_label = f"{state.time.year}年{state.time.month}月"
    person_summary = (
        f"权力真空之后，{anchor_facts[0]}紧急推举的临时治理负责人，"
        f"于{date_label}登场，维系议事、政令、奏折与任免运转。"
    )
    base_name = (
        faction.display_name
        if faction is not None
        else (region.display_name if region is not None else "行在")
    )
    authority_name = f"{base_name}临时合议"
    authority_summary = (
        "既有治理主体全部失效后，由剩余力量组成的临时合议权力，"
        "代行议事与奏折职权，直至正式治理班底重建。"
    )

    source = EntitySource(
        kind="system",
        reference=f"continuity-settlement:{settlement_id}",
        summary=person_summary,
    )
    person = PersonEntity(
        entity_id=person_id,
        display_name=person_name,
        created_by_settlement_id=settlement_id,
        origin_version_id=version_id,
        source=source,
        permissions=_permissions(_PERSON_CAPABILITIES),
        faction_ids=[faction.entity_id] if faction is not None else [],
        roles=["临时推举的治理负责人"],
    )
    authority = TemporaryAuthorityEntity(
        entity_id=authority_id,
        display_name=authority_name,
        created_by_settlement_id=settlement_id,
        origin_version_id=version_id,
        source=EntitySource(
            kind="system",
            reference=f"continuity-settlement:{settlement_id}",
            summary=authority_summary,
        ),
        permissions=_permissions(_AUTHORITY_CAPABILITIES),
        represented_entity_ids=[
            person_id,
            *([faction.entity_id] if faction is not None else []),
        ],
    )

    deltas: list[WorldDelta] = [
        EntityWorldDelta(
            delta_id=new_delta_id(),
            operation="create",
            target_entity_id=person_id,
            entity=person,
            source_proposal=_CONTINUITY_SOURCE,
        ),
        EntityWorldDelta(
            delta_id=new_delta_id(),
            operation="create",
            target_entity_id=authority_id,
            entity=authority,
            source_proposal=_CONTINUITY_SOURCE,
        ),
        RelationshipWorldDelta(
            delta_id=new_delta_id(),
            operation="create",
            from_entity_id=person_id,
            to_entity_id=authority_id,
            relationship_type="temporary_authority_membership",
            next_status="active",
            source_proposal=_CONTINUITY_SOURCE,
        ),
    ]

    return AdjudicationProposal(
        result_tier="success",
        key_factors=[
            f"权力真空：{len(state.entity_registry)} 个登记主体中无任何可参与议事的在任主体",
            *anchor_facts,
        ],
        immediate_changes=[
            f"临时治理负责人「{person_name}」登场，获得议事、奏折、任免与对话权限",
            f"临时权力「{authority_name}」成立，代行议事与奏折职权",
        ],
        long_term_risks=[
            "临时权力合法性薄弱，长期可能引发派系争权或地方观望",
        ],
        new_opportunities=[
            "可通过朝会、任命与对话重建正式治理班底",
            f"「{person_name}」可被任命为正式官职",
        ],
        execution_status="not_attempted",
        duration_candidate=Duration(unit="day", value=1),
        duration_reason="权力真空下的紧急推举与临时权力重组耗时一日",
        deltas=deltas,
        provider=ProviderAttribution(
            provider="system-continuity",
            provider_type="deterministic_derivation",
        ),
    )
