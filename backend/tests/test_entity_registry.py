from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter, ValidationError

from api.action_service import ActionService
from db import saves, worlds
from engine.settlement import (
    SettlementValidationError,
    apply_world_deltas,
    validate_adjudication_proposal,
)
from models.game import create_initial_state
from models.settlement import (
    ActionIntent,
    AdjudicationProposal,
    EntityStatusPrecondition,
    EntityTransitionWorldDelta,
    EntityWorldDelta,
    OfficeWorldDelta,
    PermissionWorldDelta,
    RelationshipWorldDelta,
    WorldDelta,
)
from models.world import (
    Duration,
    EntitySource,
    FactionEntity,
    InstitutionEntity,
    OfficeEntity,
    PermissionReference,
    PersonEntity,
    RelationshipEdge,
    new_branch_id,
    new_client_action_id,
    new_delta_id,
    new_entity_id,
    new_game_id,
    new_permission_id,
    new_relation_id,
    new_version_id,
)


def _intent(root=None) -> ActionIntent:
    root = root or SimpleNamespace(
        game_id=new_game_id(),
        branch_id=new_branch_id(),
        version_id=new_version_id(),
    )
    return ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="重组当前治理主体",
        action_kind="registry_transition",
        mode="governance",
    )


def _proposal(*deltas) -> AdjudicationProposal:
    return AdjudicationProposal(
        result_tier="success",
        key_factors=["当前主体结构需要调整"],
        immediate_changes=["主体注册表完成原子变更"],
        execution_status="completed",
        duration_candidate=Duration(unit="hour", value=1),
        duration_reason="核验并登记主体变化需要一小时",
        deltas=list(deltas),
    )


def _faction(name: str) -> FactionEntity:
    entity_id = new_entity_id()
    return FactionEntity(
        entity_id=entity_id,
        display_name=name,
        source=EntitySource(kind="adjudication", summary="测试裁决生成"),
    )


@pytest.mark.parametrize(
    ("operation", "source_count", "result_count"),
    [
        ("replace", 1, 1),
        ("split", 1, 2),
        ("merge", 2, 1),
    ],
)
def test_entity_transition_replace_split_merge_is_atomic(
    operation: str,
    source_count: int,
    result_count: int,
):
    state = create_initial_state()
    sources = [_faction(f"来源势力 {index}") for index in range(source_count)]
    results = [_faction(f"结果势力 {index}") for index in range(result_count)]
    state.entity_registry = {entity.entity_id: entity for entity in sources}
    delta = EntityTransitionWorldDelta(
        delta_id=new_delta_id(),
        operation=operation,
        sources=[
            EntityStatusPrecondition(entity_id=entity.entity_id, status="active")
            for entity in sources
        ],
        result_entities=results,
        ended_at="settlement:test-transition",
    )
    proposal = _proposal(delta)

    validate_adjudication_proposal(_intent(), state, proposal)
    changed = apply_world_deltas(state, proposal.deltas)

    assert all(state.entity_registry[item.entity_id].status == "active" for item in sources)
    assert all(changed.entity_registry[item.entity_id].status == "ended" for item in sources)
    assert all(changed.entity_registry[item.entity_id].available is False for item in sources)
    assert all(item.entity_id in changed.entity_registry for item in results)


def test_entity_transition_model_rejects_invalid_shapes_and_ids():
    source = _faction("来源")
    first = _faction("结果甲")
    second = _faction("结果乙")
    invalid_cases = [
        {
            "operation": "split",
            "sources": [EntityStatusPrecondition(entity_id=source.entity_id, status="active")],
            "result_entities": [first],
        },
        {
            "operation": "merge",
            "sources": [
                EntityStatusPrecondition(entity_id=source.entity_id, status="active"),
                EntityStatusPrecondition(entity_id=source.entity_id, status="active"),
            ],
            "result_entities": [first],
        },
        {
            "operation": "split",
            "sources": [EntityStatusPrecondition(entity_id=source.entity_id, status="active")],
            "result_entities": [first, first],
        },
        {
            "operation": "replace",
            "sources": [EntityStatusPrecondition(entity_id=source.entity_id, status="active")],
            "result_entities": [source],
        },
        {
            "operation": "split",
            "sources": [EntityStatusPrecondition(entity_id=source.entity_id, status="active")],
            "result_entities": [
                first.model_copy(update={"status": "ended", "available": False}),
                second,
            ],
        },
    ]

    for values in invalid_cases:
        with pytest.raises(ValidationError):
            EntityTransitionWorldDelta(delta_id=new_delta_id(), **values)


def test_registry_delta_union_json_round_trip_preserves_discriminated_types():
    source = _faction("来源")
    result = _faction("替代者")
    permission = PermissionReference(
        permission_id=new_permission_id(),
        capability="governance.assembly.participate",
    )
    deltas = [
        EntityWorldDelta(
            delta_id=new_delta_id(),
            operation="create",
            target_entity_id=result.entity_id,
            entity=result,
        ),
        EntityTransitionWorldDelta(
            delta_id=new_delta_id(),
            operation="replace",
            sources=[EntityStatusPrecondition(entity_id=source.entity_id, status="active")],
            result_entities=[result],
        ),
        RelationshipWorldDelta(
            delta_id=new_delta_id(),
            relationship_id=new_relation_id(),
            operation="create",
            from_entity_id=source.entity_id,
            to_entity_id=result.entity_id,
            relationship_type="supports",
            next_status="active",
        ),
        PermissionWorldDelta(
            delta_id=new_delta_id(),
            operation="grant",
            target_entity_id=result.entity_id,
            permission_id=permission.permission_id,
            permission=permission,
        ),
        OfficeWorldDelta(
            delta_id=new_delta_id(),
            operation="assign",
            office_entity_id=new_entity_id(),
            before_holder_entity_id=None,
            holder_entity_id=result.entity_id,
        ),
    ]
    adapter = TypeAdapter(WorldDelta)

    restored = [
        adapter.validate_python(delta.model_dump(mode="json"))
        for delta in deltas
    ]

    assert restored == deltas


def test_transition_cannot_leave_active_result_pointing_to_ended_source():
    state = create_initial_state()
    source = _faction("待拆分势力")
    first = _faction("新势力甲").model_copy(update={"member_ids": [source.entity_id]})
    second = _faction("新势力乙")
    state.entity_registry[source.entity_id] = source
    delta = EntityTransitionWorldDelta(
        delta_id=new_delta_id(),
        operation="split",
        sources=[EntityStatusPrecondition(entity_id=source.entity_id, status="active")],
        result_entities=[first, second],
    )
    proposal = _proposal(delta)

    with pytest.raises(SettlementValidationError) as exc_info:
        validate_adjudication_proposal(_intent(), state, proposal)
    assert exc_info.value.code == "inactive_entity_reference"
    with pytest.raises(SettlementValidationError) as exc_info:
        apply_world_deltas(state, proposal.deltas)
    assert exc_info.value.code == "inactive_entity_reference"


def test_relationship_permission_and_office_deltas_round_trip_registry_links():
    state = create_initial_state()
    old_holder_id = new_entity_id()
    authority_id = new_entity_id()
    office_id = new_entity_id()
    old_holder = PersonEntity(
        entity_id=old_holder_id,
        display_name="旧任",
        source=EntitySource(kind="system"),
        office_ids=[office_id],
    )
    authority = InstitutionEntity(
        entity_id=authority_id,
        display_name="临时议政会",
        institution_kind="council",
        source=EntitySource(kind="adjudication"),
    )
    office = OfficeEntity(
        entity_id=office_id,
        display_name="议政职责",
        source=EntitySource(kind="system"),
        holder_entity_id=old_holder_id,
        responsibility="组织议事",
    )
    state.entity_registry = {
        old_holder_id: old_holder,
        authority_id: authority,
        office_id: office,
    }
    permission = PermissionReference(
        permission_id=new_permission_id(),
        capability="governance.assembly.participate",
        scope_entity_id=office_id,
        granted_by_entity_id=old_holder_id,
    )
    relationship_id = new_relation_id()
    grant = PermissionWorldDelta(
        delta_id=new_delta_id(),
        operation="grant",
        target_entity_id=authority_id,
        permission_id=permission.permission_id,
        permission=permission,
    )
    relationship = RelationshipWorldDelta(
        delta_id=new_delta_id(),
        relationship_id=relationship_id,
        operation="create",
        from_entity_id=authority_id,
        to_entity_id=old_holder_id,
        relationship_type="succeeds",
        next_status="active",
    )
    assign = OfficeWorldDelta(
        delta_id=new_delta_id(),
        operation="assign",
        office_entity_id=office_id,
        before_holder_entity_id=old_holder_id,
        holder_entity_id=authority_id,
    )
    proposal = _proposal(grant, relationship, assign)

    validate_adjudication_proposal(_intent(), state, proposal)
    changed = apply_world_deltas(state, proposal.deltas)

    changed_authority = changed.entity_registry[authority_id]
    changed_office = changed.entity_registry[office_id]
    changed_old_holder = changed.entity_registry[old_holder_id]
    assert changed_authority.permissions == [permission]
    assert changed_authority.relationships == [
        RelationshipEdge(
            relationship_id=relationship_id,
            relationship_type="succeeds",
            from_entity_id=authority_id,
            to_entity_id=old_holder_id,
        ),
    ]
    assert isinstance(changed_office, OfficeEntity)
    assert changed_office.holder_entity_id == authority_id
    assert isinstance(changed_old_holder, PersonEntity)
    assert office_id not in changed_old_holder.office_ids

    revoke = PermissionWorldDelta(
        delta_id=new_delta_id(),
        operation="revoke",
        target_entity_id=authority_id,
        permission_id=permission.permission_id,
        before_permission=permission,
    )
    end_relationship = RelationshipWorldDelta(
        delta_id=new_delta_id(),
        relationship_id=relationship_id,
        operation="end",
        from_entity_id=authority_id,
        to_entity_id=old_holder_id,
        relationship_type="succeeds",
        before_status="active",
        next_status="ended",
    )
    vacate = OfficeWorldDelta(
        delta_id=new_delta_id(),
        operation="vacate",
        office_entity_id=office_id,
        before_holder_entity_id=authority_id,
    )
    second = _proposal(revoke, end_relationship, vacate)

    validate_adjudication_proposal(_intent(), changed, second)
    final = apply_world_deltas(changed, second.deltas)

    assert final.entity_registry[authority_id].permissions == []
    assert final.entity_registry[authority_id].relationships[0].status == "ended"
    assert isinstance(final.entity_registry[office_id], OfficeEntity)
    assert final.entity_registry[office_id].holder_entity_id is None


def test_same_batch_conflicts_fail_before_apply_and_late_failure_keeps_input_unchanged():
    state = create_initial_state()
    person_id = new_entity_id()
    office_id = new_entity_id()
    person = PersonEntity(
        entity_id=person_id,
        display_name="候选人",
        source=EntitySource(kind="system"),
    )
    office = OfficeEntity(
        entity_id=office_id,
        display_name="空缺职责",
        source=EntitySource(kind="system"),
    )
    state.entity_registry = {person_id: person, office_id: office}
    first = OfficeWorldDelta(
        delta_id=new_delta_id(),
        operation="assign",
        office_entity_id=office_id,
        before_holder_entity_id=None,
        holder_entity_id=person_id,
    )
    second = first.model_copy(update={"delta_id": new_delta_id()})

    with pytest.raises(SettlementValidationError) as exc_info:
        validate_adjudication_proposal(_intent(), state, _proposal(first, second))
    assert exc_info.value.code == "delta_conflict"

    permission = PermissionReference(
        permission_id=new_permission_id(),
        capability="governance.decree.issue",
    )
    grant = PermissionWorldDelta(
        delta_id=new_delta_id(),
        operation="grant",
        target_entity_id=person_id,
        permission_id=permission.permission_id,
        permission=permission,
    )
    stale_assignment = first.model_copy(
        update={"delta_id": new_delta_id(), "before_holder_entity_id": new_entity_id()},
    )
    before = state.model_dump(mode="json")
    with pytest.raises(SettlementValidationError) as exc_info:
        apply_world_deltas(state, [grant, stale_assignment])
    assert exc_info.value.code == "delta_precondition_failed"
    assert state.model_dump(mode="json") == before


def test_same_batch_created_office_can_be_assigned_before_its_create_delta():
    state = create_initial_state()
    holder_id = new_entity_id()
    office_id = new_entity_id()
    state.entity_registry[holder_id] = PersonEntity(
        entity_id=holder_id,
        display_name="新任",
        source=EntitySource(kind="system"),
    )
    office = OfficeEntity(
        entity_id=office_id,
        display_name="新设职责",
        source=EntitySource(kind="adjudication"),
    )
    assign = OfficeWorldDelta(
        delta_id=new_delta_id(),
        operation="assign",
        office_entity_id=office_id,
        before_holder_entity_id=None,
        holder_entity_id=holder_id,
    )
    create = EntityWorldDelta(
        delta_id=new_delta_id(),
        operation="create",
        target_entity_id=office_id,
        entity=office,
    )
    proposal = _proposal(assign, create)

    validate_adjudication_proposal(_intent(), state, proposal)
    changed = apply_world_deltas(state, proposal.deltas)

    assert isinstance(changed.entity_registry[office_id], OfficeEntity)
    assert changed.entity_registry[office_id].holder_entity_id == holder_id
    assert isinstance(changed.entity_registry[holder_id], PersonEntity)
    assert changed.entity_registry[holder_id].office_ids == [office_id]


class _StaticAdjudicator:
    def __init__(self, proposal: AdjudicationProposal):
        self.proposal = proposal

    async def adjudicate(self, intent, state):
        return self.proposal


def test_registry_batch_commits_once_and_round_trips_from_immutable_version(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "entity-registry.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    initial = worlds.load_version(root.version_id).state
    holder = next(
        entity
        for entity in initial.entity_registry.values()
        if isinstance(entity, PersonEntity) and entity.available
    )
    office_id = new_entity_id()
    office = OfficeEntity(
        entity_id=office_id,
        display_name="动态议事职责",
        source=EntitySource(kind="adjudication", summary="本次行动创建"),
        responsibility="召集可用治理主体",
    )
    permission = PermissionReference(
        permission_id=new_permission_id(),
        capability="governance.assembly.participate",
        scope_entity_id=office_id,
    )
    proposal = _proposal(
        OfficeWorldDelta(
            delta_id=new_delta_id(),
            operation="assign",
            office_entity_id=office_id,
            before_holder_entity_id=None,
            holder_entity_id=holder.entity_id,
        ),
        PermissionWorldDelta(
            delta_id=new_delta_id(),
            operation="grant",
            target_entity_id=holder.entity_id,
            permission_id=permission.permission_id,
            permission=permission,
        ),
        EntityWorldDelta(
            delta_id=new_delta_id(),
            operation="create",
            target_entity_id=office_id,
            entity=office,
        ),
    )
    intent = _intent(root)

    execution = ActionService(adjudicator=_StaticAdjudicator(proposal)).execute_sync(intent)
    reloaded = worlds.load_version(execution.result.version.version_id).state

    assert execution.result.replayed is False
    assert reloaded == execution.state
    assert reloaded.entity_registry[office_id].holder_entity_id == holder.entity_id
    assert permission in reloaded.entity_registry[holder.entity_id].permissions
    assert worlds.load_version(root.version_id).state == initial
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 2


def test_invalid_registry_proposal_has_zero_durable_effect(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "entity-registry-invalid.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    missing_entity_id = new_entity_id()
    permission = PermissionReference(
        permission_id=new_permission_id(),
        capability="governance.decree.issue",
    )
    proposal = _proposal(
        PermissionWorldDelta(
            delta_id=new_delta_id(),
            operation="grant",
            target_entity_id=missing_entity_id,
            permission_id=permission.permission_id,
            permission=permission,
        ),
    )

    with pytest.raises(SettlementValidationError) as exc_info:
        ActionService(adjudicator=_StaticAdjudicator(proposal)).execute_sync(_intent(root))

    assert exc_info.value.code == "unknown_entity_reference"
    assert worlds.get_branch_head(root.game_id, root.branch_id).version_id == root.version_id
    assert worlds.list_settlements(root.game_id, root.branch_id) == []
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 1
