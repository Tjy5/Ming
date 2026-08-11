from __future__ import annotations

from uuid import uuid4

from ai.prompts import build_global_situation, build_parse_prompt
from engine.core import detect_memorial_triggers, validate_target
from engine.entity_views import (
    appointment_actor_views,
    assembly_actor_views,
    dialogue_actor_views,
    memorial_actor_views,
    registry_actor_views,
)
from engine.execution import executor_candidates
from engine.state_consistency import (
    active_actor_names,
    roster_names,
    unavailable_actors,
    validate_narrative_text,
)
from models.enums import DecreeType, PersonnelAction
from models.game import Minister, StructuredDecree, create_initial_state
from models.world import (
    ASSEMBLY_PARTICIPATE_CAPABILITY,
    ENTITY_DIALOGUE_CAPABILITY,
    MEMORIAL_SUBMIT_CAPABILITY,
    OFFICE_APPOINTABLE_CAPABILITY,
    EntitySource,
    InstitutionEntity,
    PermissionReference,
    PersonEntity,
    VersionId,
    new_entity_id,
    new_permission_id,
)


def _permission(capability: str) -> PermissionReference:
    return PermissionReference(
        permission_id=new_permission_id(),
        capability=capability,
    )


def _state_with_registry():
    state = create_initial_state()
    state.ministers = [Minister(name="静态幽灵", faction="旧名册")]
    state.entity_registry = {}
    state.world_metadata = state.world_metadata.model_copy(
        update={"version_id": VersionId(uuid4())},
    )
    return state


def test_shared_capability_projection_filters_registry_status_and_legacy_roster():
    state = _state_with_registry()
    source = EntitySource(kind="adjudication", summary="当前分支主体")
    person_id = new_entity_id()
    ended_id = new_entity_id()
    institution_id = new_entity_id()
    permissions = [
        _permission(ASSEMBLY_PARTICIPATE_CAPABILITY),
        _permission(ENTITY_DIALOGUE_CAPABILITY),
        _permission(MEMORIAL_SUBMIT_CAPABILITY),
        _permission(OFFICE_APPOINTABLE_CAPABILITY),
    ]
    state.entity_registry[person_id] = PersonEntity(
        entity_id=person_id,
        display_name="新任参议",
        source=source,
        permissions=permissions,
    )
    state.entity_registry[ended_id] = PersonEntity(
        entity_id=ended_id,
        display_name="已故旧臣",
        status="ended",
        available=False,
        source=source,
        permissions=[_permission(ASSEMBLY_PARTICIPATE_CAPABILITY)],
    )
    state.entity_registry[institution_id] = InstitutionEntity(
        entity_id=institution_id,
        display_name="军务议事局",
        institution_kind="collective_council",
        source=source,
        permissions=[
            _permission(ASSEMBLY_PARTICIPATE_CAPABILITY),
            _permission(MEMORIAL_SUBMIT_CAPABILITY),
        ],
    )

    assert {view.entity_id for view in assembly_actor_views(state)} == {
        person_id,
        institution_id,
    }
    assert {view.entity_id for view in dialogue_actor_views(state)} == {person_id}
    assert {view.entity_id for view in memorial_actor_views(state)} == {
        person_id,
        institution_id,
    }
    assert {view.entity_id for view in appointment_actor_views(state)} == {person_id}
    assert {view.entity_id for view in registry_actor_views(state)} == {
        person_id,
        ended_id,
        institution_id,
    }
    assert all(view.display_name != "静态幽灵" for view in registry_actor_views(state))


def test_state_consistency_uses_registry_identity_and_ended_status():
    state = _state_with_registry()
    source = EntitySource(kind="adjudication", summary="当前分支主体")
    active_id = new_entity_id()
    ended_id = new_entity_id()
    state.entity_registry[active_id] = PersonEntity(
        entity_id=active_id,
        display_name="新臣甲",
        source=source,
    )
    state.entity_registry[ended_id] = PersonEntity(
        entity_id=ended_id,
        display_name="旧臣乙",
        status="ended",
        available=False,
        source=source,
    )

    assert active_actor_names(state) == {"新臣甲"}
    assert roster_names(state) == {"新臣甲", "旧臣乙"}
    assert unavailable_actors(state) == {"旧臣乙": "已终止/出局"}
    assert validate_narrative_text("新臣甲：臣请整饬军务。", state) == []
    issues = validate_narrative_text("旧臣乙上奏请战。", state)
    assert any(issue["type"] == "unavailable_actor_activity" for issue in issues)


def test_prompt_context_and_appointment_parse_candidates_use_projection():
    state = _state_with_registry()
    source = EntitySource(kind="adjudication", summary="当前分支推举")
    person_id = new_entity_id()
    state.entity_registry[person_id] = PersonEntity(
        entity_id=person_id,
        display_name="动态任命人",
        roles=["候补参政"],
        source=source,
        permissions=[
            _permission(MEMORIAL_SUBMIT_CAPABILITY),
            _permission(OFFICE_APPOINTABLE_CAPABILITY),
        ],
    )

    situation = build_global_situation(state)
    parse_prompt = build_parse_prompt("任命动态任命人为中书参政", state)

    assert "动态任命人" in situation
    assert str(person_id) in situation
    assert OFFICE_APPOINTABLE_CAPABILITY in situation
    assert "静态幽灵" not in situation
    assert f"动态任命人[entity_id={person_id};type=person]" in parse_prompt


def test_memorial_author_keeps_registry_identity_and_capability_evidence():
    state = _state_with_registry()
    source = EntitySource(kind="adjudication", summary="当前分支机构上奏")
    institution_id = new_entity_id()
    state.entity_registry[institution_id] = InstitutionEntity(
        entity_id=institution_id,
        display_name="军务急报局",
        institution_kind="memorial_office",
        source=source,
        permissions=[_permission(MEMORIAL_SUBMIT_CAPABILITY)],
    )
    for faction in state.factions:
        faction.satisfaction = 100
        faction.rebellion_risk = 0
    for region in state.regions:
        region.stability = 100
    state.regions[0].stability = 0
    state.military_morale = 100
    state.military_strength = 100

    memorials = detect_memorial_triggers(state, {})

    assert memorials
    memorial = memorials[0]
    assert memorial.author_name == "军务急报局"
    assert memorial.author_entity_id == institution_id
    assert memorial.author_entity_type == "institution"
    assert memorial.author_capabilities == [MEMORIAL_SUBMIT_CAPABILITY]
    assert memorial.author_capability_sources[0].startswith("permission:")
    assert memorial.model_validate(memorial.model_dump()).author_entity_id == institution_id


def test_appointment_validation_resolves_stable_registry_id():
    state = _state_with_registry()
    source = EntitySource(kind="adjudication", summary="当前分支候补官员")
    person_id = new_entity_id()
    state.entity_registry[person_id] = PersonEntity(
        entity_id=person_id,
        display_name="候补参政",
        source=source,
        permissions=[_permission(OFFICE_APPOINTABLE_CAPABILITY)],
    )
    decree = StructuredDecree(
        type=DecreeType.PERSONNEL,
        target=str(person_id),
        sub_action=PersonnelAction.APPOINT,
        parameters={"position": "中书参政"},
    )

    assert validate_target(decree, state) is None

    state.entity_registry[person_id] = state.entity_registry[person_id].model_copy(
        update={"permissions": []},
    )
    assert validate_target(decree, state) == "任免目标人物不存在"

    state.entity_registry[person_id] = state.entity_registry[person_id].model_copy(
        update={
            "status": "ended",
            "available": False,
            "permissions": [_permission(OFFICE_APPOINTABLE_CAPABILITY)],
        },
    )
    assert validate_target(decree, state) == "任免目标人物不存在"


def test_executor_candidates_consume_shared_registry_projection():
    state = _state_with_registry()
    source = EntitySource(kind="adjudication", summary="当前分支执行主体")
    institution_id = new_entity_id()
    ended_id = new_entity_id()
    state.entity_registry[institution_id] = InstitutionEntity(
        entity_id=institution_id,
        display_name="行营转运司",
        institution_kind="logistics_office",
        source=source,
        permissions=[_permission("world.action.execute")],
    )
    state.entity_registry[ended_id] = PersonEntity(
        entity_id=ended_id,
        display_name="失效执行者",
        status="ended",
        available=False,
        source=source,
        permissions=[_permission("world.action.execute")],
    )

    candidates = executor_candidates(state, action_kind="governance")
    by_id = {item.executor.actual_executor_id: item for item in candidates}

    assert by_id[institution_id].available is True
    assert by_id[institution_id].authority == ["world.action.execute"]
    assert by_id[ended_id].available is False
