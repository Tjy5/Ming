from __future__ import annotations

from collections.abc import Hashable, Sequence
from math import isfinite
from numbers import Real
from uuid import UUID

from pydantic import ValidationError

from models.game import GameState, clamp_state
from models.settlement import (
    ActionIntent,
    AdjudicationProposal,
    CommitmentWorldDelta,
    CompatibilityStatePatchDelta,
    ElapsedStatePatchDelta,
    EntityTransitionWorldDelta,
    EntityWorldDelta,
    LifecycleWorldDelta,
    MetricWorldDelta,
    ModifierWorldDelta,
    OfficeWorldDelta,
    PermissionWorldDelta,
    PlayerWorldDelta,
    RelationshipWorldDelta,
    WorldDelta,
)
from models.world import (
    EntityId,
    OfficeEntity,
    PermissionId,
    PermissionReference,
    PersonEntity,
    RelationId,
    RelationshipEdge,
    SettlementId,
    VersionId,
    WorldEntity,
    validate_entity_registry,
)
from models.world_state import AppliedMetricAttribution, ExecutorFacts, RollRecord

from .world_state import (
    WorldStateValidationError,
    apply_commitment_delta,
    apply_metric_delta as apply_typed_metric_delta,
    apply_modifier_delta,
)


_WORLD_METRIC_FIELDS = frozenset(
    {
        "national_treasury",
        "imperial_treasury",
        "grain",
        "population",
        "military_strength",
        "civil_morale",
        "military_morale",
        "court_prestige",
        "chapter_turns",
        "decree_count",
        "consecutive_waits",
    },
)
_PROTECTED_ENTITY_FIELDS = frozenset(
    {
        "entity_id",
        "entity_type",
        "created_by_settlement_id",
        "origin_version_id",
        "source",
    },
)
_DEDICATED_REGISTRY_FIELDS = frozenset(
    {
        "permissions",
        "relationships",
        "office_ids",
        "holder_entity_id",
    },
)
ELAPSED_PATCH_FIELDS = frozenset(
    {
        "national_treasury",
        "imperial_treasury",
        "grain",
        "population",
        "military_strength",
        "civil_morale",
        "military_morale",
        "court_prestige",
        "factions",
        "regions",
        "ministers",
        "active_events",
        "history_log",
        "decree_count",
        "decrees_this_month",
        "event_cooldowns",
        "resolved_script_ids",
        "trigger_decisions",
        "memorials",
        "memorial_cooldowns",
        "loyalty_zero_triggered",
        "consecutive_waits",
        "character_sheets",
        "growth_log",
        "active_policies",
    },
)
COMPATIBILITY_PATCH_FIELDS = frozenset(
    {
        "phase",
        "chapter",
        "chapter_turns",
        "national_treasury",
        "imperial_treasury",
        "grain",
        "population",
        "military_strength",
        "civil_morale",
        "military_morale",
        "court_prestige",
        "factions",
        "regions",
        "ministers",
        "active_events",
        "history_log",
        "decree_count",
        "decrees_this_month",
        "event_cooldowns",
        "resolved_script_ids",
        "trigger_decisions",
        "memorials",
        "memorial_cooldowns",
        "last_assembly",
        "loyalty_zero_triggered",
        "last_assembly_month",
        "consecutive_waits",
        "minister_conversations",
        "character_sheets",
        "growth_log",
        "execution_rng_seed",
        "active_policies",
    },
)
_UNORDERED_PATCH_FIELDS = frozenset(
    {
        "resolved_script_ids",
        "loyalty_zero_triggered",
    },
)

# Lifecycle currently owns only the minimal goal projection.  The persisted
# player status intentionally stores visible/actionable goal ids rather than a
# second status map, so ``available`` and ``active`` are equivalent visible
# states at this boundary.  Terminal states are represented by absence.
_GOAL_VISIBLE_STATUSES = frozenset({"available", "active"})
_GOAL_TERMINAL_STATUSES = frozenset({"completed", "blocked", "ended"})
_GOAL_STATUSES = _GOAL_VISIBLE_STATUSES | _GOAL_TERMINAL_STATUSES


class SettlementValidationError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        delta_id: object | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.delta_id = str(delta_id) if delta_id is not None else None
        super().__init__(message)


def _fail(
    code: str,
    message: str,
    *,
    delta: WorldDelta | None = None,
) -> None:
    raise SettlementValidationError(
        code,
        message,
        delta_id=delta.delta_id if delta is not None else None,
    )


def _is_number(value: object) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and isfinite(float(value))
    )


def _known_entity_ids(
    state: GameState,
    proposal: AdjudicationProposal,
) -> set[EntityId]:
    known = set(state.entity_registry)
    for delta in proposal.deltas:
        if isinstance(delta, EntityWorldDelta) and delta.operation == "create":
            known.add(delta.target_entity_id)
        elif isinstance(delta, EntityTransitionWorldDelta):
            known.update(entity.entity_id for entity in delta.result_entities)
    return known


def _proposal_entities(
    state: GameState,
    proposal: AdjudicationProposal,
) -> dict[EntityId, WorldEntity]:
    entities = dict(state.entity_registry)
    for delta in proposal.deltas:
        if (
            isinstance(delta, EntityWorldDelta)
            and delta.operation == "create"
            and delta.entity is not None
        ):
            entities[delta.target_entity_id] = delta.entity
        elif isinstance(delta, EntityTransitionWorldDelta):
            entities.update(
                (entity.entity_id, entity) for entity in delta.result_entities
            )
    return entities


def _ending_entity_ids(proposal: AdjudicationProposal) -> set[EntityId]:
    return _ending_entity_ids_from_deltas(proposal.deltas)


def _ending_entity_ids_from_deltas(
    deltas: Sequence[WorldDelta],
) -> set[EntityId]:
    ending: set[EntityId] = set()
    for delta in deltas:
        if isinstance(delta, EntityWorldDelta) and delta.operation == "end":
            ending.add(delta.target_entity_id)
        elif isinstance(delta, EntityTransitionWorldDelta):
            ending.update(source.entity_id for source in delta.sources)
    return ending


def _require_entity(
    entity_id: EntityId | None,
    known: set[EntityId],
    *,
    label: str,
    delta: WorldDelta | None = None,
) -> None:
    if entity_id is None or entity_id not in known:
        _fail(
            "unknown_entity_reference",
            f"{label} 引用了当前世界中不存在的主体",
            delta=delta,
        )


def _validate_entity_payload_references(
    entity: WorldEntity,
    known: set[EntityId],
    delta: WorldDelta,
) -> None:
    for permission in entity.permissions:
        for reference, label in (
            (permission.scope_entity_id, "permission.scope_entity_id"),
            (permission.granted_by_entity_id, "permission.granted_by_entity_id"),
        ):
            if reference is not None:
                _require_entity(reference, known, label=label, delta=delta)

    for relationship in entity.relationships:
        if relationship.from_entity_id != entity.entity_id:
            _fail(
                "invalid_relationship",
                "主体内嵌关系的 from_entity_id 必须等于主体自身 ID",
                delta=delta,
            )
        _require_entity(
            relationship.to_entity_id,
            known,
            label="relationship.to_entity_id",
            delta=delta,
        )

    list_reference_fields = (
        "faction_ids",
        "office_ids",
        "member_ids",
        "represented_entity_ids",
    )
    for field in list_reference_fields:
        for reference in getattr(entity, field, []):
            _require_entity(reference, known, label=field, delta=delta)
    for field in ("holder_entity_id", "controller_entity_id"):
        reference = getattr(entity, field, None)
        if reference is not None:
            _require_entity(reference, known, label=field, delta=delta)


def _validate_entity_payload_liveness(
    entity: WorldEntity,
    ending: set[EntityId],
    delta: WorldDelta,
) -> None:
    for permission in entity.permissions:
        if permission.scope_entity_id in ending:
            _fail(
                "inactive_entity_reference",
                "active permission 不能以本批次结束的主体为作用域",
                delta=delta,
            )
    for relationship in entity.relationships:
        if relationship.status == "active" and relationship.to_entity_id in ending:
            _fail(
                "inactive_entity_reference",
                "active relationship 不能指向本批次结束的主体",
                delta=delta,
            )
    for field in (
        "faction_ids",
        "office_ids",
        "member_ids",
        "represented_entity_ids",
    ):
        references = list(getattr(entity, field, []))
        if entity.entity_id in references:
            _fail(
                "invalid_entity_reference",
                f"{field} 不能引用主体自身",
                delta=delta,
            )
        if any(reference in ending for reference in references):
            _fail(
                "inactive_entity_reference",
                f"{field} 不能引用本批次结束的主体",
                delta=delta,
            )
    for field in ("holder_entity_id", "controller_entity_id"):
        reference = getattr(entity, field, None)
        if reference == entity.entity_id:
            _fail(
                "invalid_entity_reference",
                f"{field} 不能引用主体自身",
                delta=delta,
            )
        if reference in ending:
            _fail(
                "inactive_entity_reference",
                f"{field} 不能引用本批次结束的主体",
                delta=delta,
            )


def _validate_apply_batch(deltas: Sequence[WorldDelta]) -> None:
    """Defend common batch/liveness rules when the pure applier is called directly."""

    seen_delta_ids: set[object] = set()
    seen_conflicts: set[Hashable] = set()
    ending = _ending_entity_ids_from_deltas(deltas)
    terminal_death_proposed = any(
        isinstance(delta, PlayerWorldDelta) and delta.operation == "death"
        for delta in deltas
    )
    for delta in deltas:
        if delta.delta_id in seen_delta_ids:
            _fail(
                "duplicate_delta_id",
                "同一应用批次包含重复 delta_id",
                delta=delta,
            )
        seen_delta_ids.add(delta.delta_id)
        if isinstance(
            delta,
            (
                EntityWorldDelta,
                EntityTransitionWorldDelta,
                RelationshipWorldDelta,
                PermissionWorldDelta,
                OfficeWorldDelta,
                LifecycleWorldDelta,
            ),
        ):
            conflict_keys = _delta_conflict_keys(delta)
            if conflict_keys & seen_conflicts:
                _fail(
                    "delta_conflict",
                    "同一应用批次对同一 registry 目标给出了冲突变化",
                    delta=delta,
                )
            seen_conflicts.update(conflict_keys)

        if isinstance(delta, EntityWorldDelta):
            if delta.operation == "create":
                if (
                    delta.entity is None
                    or delta.entity.entity_id != delta.target_entity_id
                    or delta.before_status is not None
                    or delta.changes
                ):
                    _fail(
                        "invalid_entity_payload",
                        "create delta 只能携带 ID 一致的完整主体",
                        delta=delta,
                    )
                _validate_entity_payload_liveness(delta.entity, ending, delta)
            elif delta.entity is not None:
                _fail(
                    "invalid_entity_payload",
                    "update/end delta 不得替换完整主体对象",
                    delta=delta,
                )
            change_fields: set[str] = set()
            for change in delta.changes:
                if change.field in change_fields:
                    _fail(
                        "delta_conflict",
                        "同一主体 delta 重复修改相同字段",
                        delta=delta,
                    )
                change_fields.add(change.field)
                if delta.operation == "end" and change.field in {"status", "available"}:
                    _fail(
                        "invalid_entity_end",
                        "end delta 不得通过 changes 恢复主体状态或可用性",
                        delta=delta,
                    )
        elif isinstance(delta, EntityTransitionWorldDelta):
            for entity in delta.result_entities:
                _validate_entity_payload_liveness(entity, ending, delta)
        elif isinstance(delta, RelationshipWorldDelta):
            if delta.operation == "create" and (
                delta.before_status is not None
                or delta.next_status not in {None, "active"}
            ):
                _fail(
                    "invalid_relationship",
                    "create relationship 必须从不存在状态创建 active 关系",
                    delta=delta,
                )
            if delta.operation == "update" and delta.next_status is None:
                _fail(
                    "invalid_relationship",
                    "update relationship 必须提供 next_status",
                    delta=delta,
                )
            if delta.operation == "end" and delta.next_status not in {None, "ended"}:
                _fail(
                    "invalid_relationship",
                    "end relationship 的 next_status 只能是 ended",
                    delta=delta,
                )
            if delta.operation == "create" and (
                delta.from_entity_id in ending or delta.to_entity_id in ending
            ):
                _fail(
                    "inactive_entity_reference",
                    "不能为本批次结束的主体创建 active 关系",
                    delta=delta,
                )
        elif isinstance(delta, PermissionWorldDelta) and delta.operation == "grant":
            if delta.target_entity_id in ending:
                _fail(
                    "inactive_entity_reference",
                    "不能向本批次结束的主体授予权限",
                    delta=delta,
                )
            if delta.permission is not None and delta.permission.scope_entity_id in ending:
                _fail(
                    "inactive_entity_reference",
                    "active permission 不能以本批次结束的主体为作用域",
                    delta=delta,
                )
        elif (
            isinstance(delta, OfficeWorldDelta)
            and delta.operation == "assign"
            and delta.holder_entity_id in ending
        ):
            _fail(
                "inactive_entity_reference",
                "不能任命本批次结束的主体",
                delta=delta,
            )
        elif isinstance(delta, LifecycleWorldDelta):
            # This batch-level check catches a lifecycle add ordered before a
            # death delta; the player must never end a terminal settlement with
            # a newly-created actionable goal.
            if terminal_death_proposed and delta.next_status in _GOAL_VISIBLE_STATUSES:
                _fail(
                    "dead_player_goal_transition",
                    "同批终局行动不得创建新的 actionable goal",
                    delta=delta,
                )


def _delta_conflict_keys(delta: WorldDelta) -> set[Hashable]:
    if isinstance(delta, MetricWorldDelta):
        return {("metric", delta.target_scope, delta.target_id, delta.field)}
    if isinstance(delta, EntityWorldDelta):
        return {("entity", delta.target_entity_id)}
    if isinstance(delta, EntityTransitionWorldDelta):
        return {
            ("entity", entity_id)
            for entity_id in (
                *(source.entity_id for source in delta.sources),
                *(entity.entity_id for entity in delta.result_entities),
            )
        }
    if isinstance(delta, RelationshipWorldDelta):
        return {
            (
                "relationship",
                delta.relationship_id,
                delta.from_entity_id,
                delta.to_entity_id,
                delta.relationship_type,
            ),
        }
    if isinstance(delta, PermissionWorldDelta):
        return {("permission", delta.target_entity_id, delta.permission_id)}
    if isinstance(delta, OfficeWorldDelta):
        return {("office", delta.office_entity_id)}
    if isinstance(delta, LifecycleWorldDelta):
        return {("lifecycle", delta.transition_type, delta.transition_id)}
    if isinstance(delta, PlayerWorldDelta):
        return {("player", delta.operation)}
    if isinstance(delta, ModifierWorldDelta):
        return {("modifier", delta.modifier_id)}
    if isinstance(delta, CommitmentWorldDelta):
        return {("commitment", delta.commitment_id)}
    if isinstance(delta, ElapsedStatePatchDelta):
        return {("elapsed_state_patch", tuple(sorted(delta.after_fields)))}
    if isinstance(delta, CompatibilityStatePatchDelta):
        return {("compatibility_state_patch", tuple(sorted(delta.after_fields)))}
    raise TypeError(f"Unsupported world delta: {type(delta).__name__}")


def _validate_lifecycle_goal_delta(
    state: GameState,
    delta: LifecycleWorldDelta,
    *,
    terminal_death_proposed: bool = False,
) -> bool:
    """Validate and classify the small, durable lifecycle goal contract.

    ``PlayerWorldStatus.actionable_goal_ids`` is the sole committed projection
    for visible goals.  We therefore compare preconditions against membership,
    accepting either visible label (``available``/``active``), and treat
    completed/blocked/ended as non-visible.  Missing removals without an
    explicit terminal before status are rejected instead of being silently
    ignored.

    Returns whether the transition is a visible (goal-creating) transition.
    """

    if delta.transition_type != "goal":
        _fail(
            "sibling_contract_unavailable",
            "当前 settlement 仅支持 typed goal lifecycle delta",
            delta=delta,
        )
    if not delta.transition_id.strip():
        _fail(
            "invalid_lifecycle_transition",
            "goal transition_id 不能为空",
            delta=delta,
        )
    if delta.next_status not in _GOAL_STATUSES:
        _fail(
            "invalid_lifecycle_transition",
            "goal next_status 必须是 available、active、completed、blocked 或 ended",
            delta=delta,
        )
    if delta.before_status is not None and delta.before_status not in _GOAL_STATUSES:
        _fail(
            "invalid_lifecycle_transition",
            "goal before_status 不是受支持的生命周期状态",
            delta=delta,
        )

    status = state.player_world_status
    goal_ids = status.actionable_goal_ids
    exists = delta.transition_id in goal_ids
    visible = delta.next_status in _GOAL_VISIBLE_STATUSES

    # A death delta in the same batch must never be able to create a goal by
    # ordering the lifecycle item before the player transition.
    if (status.life_status == "dead" or terminal_death_proposed) and visible:
        _fail(
            "dead_player_goal_transition",
            "dead player 或同批终局行动不得创建新的 actionable goal",
            delta=delta,
        )

    if delta.before_status is not None:
        expected_exists = delta.before_status in _GOAL_VISIBLE_STATUSES
        if exists != expected_exists:
            _fail(
                "lifecycle_goal_precondition_failed",
                "goal before_status 与当前可见状态/存在性不一致",
                delta=delta,
            )
    elif not visible and not exists:
        _fail(
            "lifecycle_goal_not_found",
            "完成、阻塞或结束 goal 必须引用当前可见目标，或声明其终态 before_status",
            delta=delta,
        )
    return visible


def _apply_lifecycle_goal_delta(state: GameState, delta: LifecycleWorldDelta) -> None:
    """Apply a validated goal transition without duplicating actionable ids."""

    _validate_lifecycle_goal_delta(state, delta)
    current = list(state.player_world_status.actionable_goal_ids)
    if delta.next_status in _GOAL_VISIBLE_STATUSES:
        if delta.transition_id not in current:
            current.append(delta.transition_id)
        else:
            # Repair only this target's duplicate entries; unrelated legacy
            # ids remain untouched and no duplicate is introduced by retry.
            seen = False
            normalized: list[str] = []
            for goal_id in current:
                if goal_id == delta.transition_id:
                    if seen:
                        continue
                    seen = True
                normalized.append(goal_id)
            current = normalized
    else:
        current = [goal_id for goal_id in current if goal_id != delta.transition_id]
    state.player_world_status = state.player_world_status.model_copy(
        update={"actionable_goal_ids": current},
    )


def _relationship_id(delta: RelationshipWorldDelta) -> RelationId:
    return delta.relationship_id or RelationId(UUID(str(delta.delta_id)))


def _relationship_matches(
    source: WorldEntity,
    delta: RelationshipWorldDelta,
) -> list[tuple[int, RelationshipEdge]]:
    return [
        (index, edge)
        for index, edge in enumerate(source.relationships)
        if edge.from_entity_id == delta.from_entity_id
        and edge.to_entity_id == delta.to_entity_id
        and edge.relationship_type == delta.relationship_type
        and (
            delta.relationship_id is None
            or edge.relationship_id == delta.relationship_id
        )
    ]


def _permission_matches(
    entity: WorldEntity,
    permission_id: PermissionId,
) -> list[tuple[int, PermissionReference]]:
    return [
        (index, permission)
        for index, permission in enumerate(entity.permissions)
        if permission.permission_id == permission_id
    ]


def validate_adjudication_proposal(
    intent: ActionIntent,
    state: GameState,
    proposal: AdjudicationProposal,
    *,
    allow_terminal_death: bool = False,
) -> None:
    """Validate sandbox-owned proposal, reference, and batch-conflict rules.

    Numeric bounds and sibling-owned time/RNG/modifier rules are deliberately
    outside this function. This boundary proves that every referenced record is
    part of the current snapshot or is created by the same proposal.
    """

    seen_delta_ids: set[object] = set()
    seen_conflicts: set[Hashable] = set()
    known = _known_entity_ids(state, proposal)
    proposed_entities = _proposal_entities(state, proposal)
    ending_entity_ids = _ending_entity_ids(proposal)
    relationship_id_values = [
        relationship.relationship_id
        for entity in proposed_entities.values()
        for relationship in entity.relationships
    ]
    permission_id_values = [
        permission.permission_id
        for entity in proposed_entities.values()
        for permission in entity.permissions
    ]
    if len(relationship_id_values) != len(set(relationship_id_values)):
        _fail(
            "duplicate_registry_identity",
            "同一主体注册表包含重复 relationship_id",
        )
    if len(permission_id_values) != len(set(permission_id_values)):
        _fail(
            "duplicate_registry_identity",
            "同一主体注册表包含重复 permission_id",
        )
    relationship_ids = set(relationship_id_values)
    permission_ids = set(permission_id_values)
    player_entity_id = state.player_world_status.player_character_id
    terminal_death_proposed = any(
        isinstance(candidate, PlayerWorldDelta) and candidate.operation == "death"
        for candidate in proposal.deltas
    )

    for reference, label in (
        (intent.requested_executor_id, "requested_executor_id"),
        (intent.target_region_id, "target_region_id"),
        (intent.replacement_executor_id, "replacement_executor_id"),
    ):
        if reference is not None:
            _require_entity(reference, known, label=label)
    for entity_id in intent.target_entity_ids:
        _require_entity(entity_id, known, label="target_entity_ids")

    if intent.activity_command == "continue":
        if proposal.activity_decision is None:
            _fail(
                "activity_decision_required",
                "活动检查点复裁必须返回结构化 activity_decision",
            )
        if proposal.activity_candidate is not None or proposal.duration_candidate is not None:
            _fail(
                "invalid_activity_checkpoint_proposal",
                "活动检查点不得创建嵌套 activity 或再次提交已经过时间",
            )
    elif intent.activity_command is None:
        if proposal.activity_decision is not None:
            _fail(
                "unexpected_activity_decision",
                "普通行动不得携带 activity checkpoint decision",
            )
        if proposal.duration_candidate is None:
            _fail(
                "duration_required",
                "每个提交的世界行动必须包含结构化正耗时",
            )
    elif proposal.activity_candidate is not None or proposal.activity_decision is not None:
        _fail(
            "unexpected_activity_adjudication",
            "暂停、取消、恢复、改道或改派命令不接受新的 activity 裁决",
        )

    if (
        intent.requested_executor_id is not None
        and proposal.requested_executor_id != intent.requested_executor_id
    ):
        _fail(
            "requested_executor_mismatch",
            "裁决结果不得静默替换玩家指定的执行者",
        )
    if proposal.requested_executor_id is not None:
        _require_entity(
            proposal.requested_executor_id,
            known,
            label="proposal.requested_executor_id",
        )
    if proposal.actual_executor_id is not None:
        _require_entity(
            proposal.actual_executor_id,
            known,
            label="proposal.actual_executor_id",
        )

    for delta in proposal.deltas:
        if delta.delta_id in seen_delta_ids:
            _fail(
                "duplicate_delta_id",
                "同一裁决批次包含重复 delta_id",
                delta=delta,
            )
        seen_delta_ids.add(delta.delta_id)

        conflict_keys = _delta_conflict_keys(delta)
        if conflict_keys & seen_conflicts:
            _fail(
                "delta_conflict",
                "同一裁决批次对同一目标给出了冲突变化",
                delta=delta,
            )
        seen_conflicts.update(conflict_keys)

        if isinstance(delta, MetricWorldDelta):
            if delta.target_scope == "world":
                if delta.target_id is not None:
                    _fail(
                        "invalid_delta_target",
                        "world metric delta 不得携带 target_id",
                        delta=delta,
                    )
            else:
                _require_entity(
                    delta.target_id,
                    known,
                    label=f"{delta.target_scope} metric target",
                    delta=delta,
                )
            if delta.operation == "increment" and (
                not _is_number(delta.before_value) or not _is_number(delta.value)
            ):
                _fail(
                    "invalid_delta_value",
                    "increment delta 的 before_value 与 value 必须是有限数值",
                    delta=delta,
                )
            continue

        if isinstance(delta, EntityWorldDelta):
            exists_before = delta.target_entity_id in state.entity_registry
            if delta.operation == "create":
                if exists_before:
                    _fail(
                        "entity_already_exists",
                        "create delta 的主体 ID 已存在",
                        delta=delta,
                    )
                if delta.entity is None or delta.entity.entity_id != delta.target_entity_id:
                    _fail(
                        "invalid_entity_payload",
                        "create delta 必须携带 ID 一致的完整主体",
                        delta=delta,
                    )
                if delta.before_status is not None or delta.changes:
                    _fail(
                        "invalid_entity_payload",
                        "create delta 只能携带完整主体，不能携带旧状态或字段 patch",
                        delta=delta,
                    )
                _validate_entity_payload_references(delta.entity, known, delta)
                _validate_entity_payload_liveness(
                    delta.entity,
                    ending_entity_ids,
                    delta,
                )
            else:
                _require_entity(
                    delta.target_entity_id,
                    set(state.entity_registry),
                    label="entity delta target",
                    delta=delta,
                )
                if delta.entity is not None:
                    _fail(
                        "invalid_entity_payload",
                        "update/end delta 不得替换完整主体对象",
                        delta=delta,
                    )
                current = state.entity_registry[delta.target_entity_id]
                if delta.before_status is not None and current.status != delta.before_status:
                    _fail(
                        "delta_precondition_failed",
                        "entity before_status 与当前世界快照不一致",
                        delta=delta,
                    )
                if delta.target_entity_id == player_entity_id and (
                    delta.operation == "end"
                    or any(
                        change.field in {"status", "available"}
                        for change in delta.changes
                    )
                ):
                    _fail(
                        "player_identity_regression",
                        "稳定玩家主体的生命周期只能由 player/terminal contract 改变",
                        delta=delta,
                    )
            change_fields: set[str] = set()
            for change in delta.changes:
                if change.field in change_fields:
                    _fail(
                        "delta_conflict",
                        "同一主体 delta 重复修改相同字段",
                        delta=delta,
                    )
                if change.field in _PROTECTED_ENTITY_FIELDS:
                    _fail(
                        "protected_entity_field",
                        "主体身份、类型和来源字段不能由普通 update delta 改写",
                        delta=delta,
                    )
                if change.field in _DEDICATED_REGISTRY_FIELDS:
                    _fail(
                        "dedicated_registry_delta_required",
                        "关系、权限和官职字段必须使用专用 registry delta",
                        delta=delta,
                    )
                if delta.operation == "end" and change.field in {"status", "available"}:
                    _fail(
                        "invalid_entity_end",
                        "end delta 不得通过 changes 恢复主体状态或可用性",
                        delta=delta,
                    )
                change_fields.add(change.field)
            continue

        if isinstance(delta, EntityTransitionWorldDelta):
            source_entities: list[WorldEntity] = []
            for source in delta.sources:
                _require_entity(
                    source.entity_id,
                    set(state.entity_registry),
                    label="entity transition source",
                    delta=delta,
                )
                current = state.entity_registry[source.entity_id]
                if current.status != source.status:
                    _fail(
                        "delta_precondition_failed",
                        "entity transition source status 与当前世界快照不一致",
                        delta=delta,
                    )
                if current.status == "ended":
                    _fail(
                        "invalid_entity_transition",
                        "replace/split/merge 不能重新消费已结束主体",
                        delta=delta,
                    )
                if source.entity_id == player_entity_id:
                    _fail(
                        "player_identity_regression",
                        "稳定玩家主体不能被 replace/split/merge",
                        delta=delta,
                    )
                source_entities.append(current)
            for entity in delta.result_entities:
                if entity.entity_id in state.entity_registry:
                    _fail(
                        "entity_already_exists",
                        "entity transition 的结果主体 ID 已存在",
                        delta=delta,
                    )
                _validate_entity_payload_references(entity, known, delta)
                _validate_entity_payload_liveness(
                    entity,
                    ending_entity_ids,
                    delta,
                )
            if delta.operation in {"split", "merge"}:
                transition_types = {
                    entity.entity_type
                    for entity in [*source_entities, *delta.result_entities]
                }
                if (
                    len(transition_types) != 1
                    or not transition_types.issubset({"faction", "institution"})
                ):
                    _fail(
                        "invalid_entity_transition",
                        "split/merge 只能在同类型的势力或机构主体之间进行",
                        delta=delta,
                    )
            continue

        if isinstance(delta, RelationshipWorldDelta):
            if delta.operation not in {"create", "update", "end"}:
                _fail(
                    "dedicated_registry_delta_required",
                    "权限授予、撤销和任命必须使用 permission/office delta",
                    delta=delta,
                )
            _require_entity(
                delta.from_entity_id,
                known,
                label="relationship.from_entity_id",
                delta=delta,
            )
            _require_entity(
                delta.to_entity_id,
                known,
                label="relationship.to_entity_id",
                delta=delta,
            )
            if delta.from_entity_id == delta.to_entity_id:
                _fail(
                    "invalid_relationship",
                    "关系边不能引用同一主体作为两端",
                    delta=delta,
                )
            source = proposed_entities[delta.from_entity_id]
            matches = _relationship_matches(source, delta)
            if delta.operation == "create":
                if delta.before_status is not None or delta.next_status not in {None, "active"}:
                    _fail(
                        "invalid_relationship",
                        "create relationship 必须从不存在状态创建 active 关系",
                        delta=delta,
                    )
                relationship_id = _relationship_id(delta)
                if relationship_id in relationship_ids or matches:
                    _fail(
                        "relationship_already_exists",
                        "关系 ID 或关系边已存在",
                        delta=delta,
                    )
                relationship_ids.add(relationship_id)
                if (
                    delta.from_entity_id in ending_entity_ids
                    or delta.to_entity_id in ending_entity_ids
                ):
                    _fail(
                        "inactive_entity_reference",
                        "不能为本批次结束的主体创建 active 关系",
                        delta=delta,
                    )
            else:
                if len(matches) != 1:
                    _fail(
                        "relationship_not_found",
                        "update/end relationship 必须引用唯一的现有关系边",
                        delta=delta,
                    )
                edge = matches[0][1]
                if delta.before_status is None or edge.status != delta.before_status:
                    _fail(
                        "delta_precondition_failed",
                        "relationship before_status 与当前世界快照不一致",
                        delta=delta,
                    )
                if delta.operation == "update" and delta.next_status is None:
                    _fail(
                        "invalid_relationship",
                        "update relationship 必须提供 next_status",
                        delta=delta,
                    )
                if delta.operation == "end" and delta.next_status not in {None, "ended"}:
                    _fail(
                        "invalid_relationship",
                        "end relationship 的 next_status 只能是 ended",
                        delta=delta,
                    )
            continue

        if isinstance(delta, PermissionWorldDelta):
            _require_entity(
                delta.target_entity_id,
                known,
                label="permission target",
                delta=delta,
            )
            target = proposed_entities[delta.target_entity_id]
            matches = _permission_matches(target, delta.permission_id)
            if delta.operation == "grant":
                if delta.target_entity_id in ending_entity_ids:
                    _fail(
                        "inactive_entity_reference",
                        "不能向本批次结束的主体授予权限",
                        delta=delta,
                    )
                if delta.permission is None:
                    _fail("invalid_permission", "grant delta 缺少权限记录", delta=delta)
                if delta.permission_id in permission_ids or matches:
                    _fail(
                        "permission_already_exists",
                        "permission_id 已存在",
                        delta=delta,
                    )
                for reference, label in (
                    (delta.permission.scope_entity_id, "permission.scope_entity_id"),
                    (delta.permission.granted_by_entity_id, "permission.granted_by_entity_id"),
                ):
                    if reference is not None:
                        _require_entity(reference, known, label=label, delta=delta)
                permission_ids.add(delta.permission_id)
            elif len(matches) != 1 or matches[0][1] != delta.before_permission:
                _fail(
                    "delta_precondition_failed",
                    "permission revoke 与当前权限记录不一致",
                    delta=delta,
                )
            continue

        if isinstance(delta, OfficeWorldDelta):
            _require_entity(
                delta.office_entity_id,
                known,
                label="office entity",
                delta=delta,
            )
            office = proposed_entities[delta.office_entity_id]
            if not isinstance(office, OfficeEntity):
                _fail(
                    "invalid_office_reference",
                    "office delta 必须引用 OfficeEntity",
                    delta=delta,
                )
            if office.holder_entity_id != delta.before_holder_entity_id:
                _fail(
                    "delta_precondition_failed",
                    "office before_holder_entity_id 与当前世界快照不一致",
                    delta=delta,
                )
            if delta.operation == "assign":
                _require_entity(
                    delta.holder_entity_id,
                    known,
                    label="office holder",
                    delta=delta,
                )
                if delta.holder_entity_id in ending_entity_ids:
                    _fail(
                        "inactive_entity_reference",
                        "不能任命本批次结束的主体",
                        delta=delta,
                    )
                holder = proposed_entities[delta.holder_entity_id]
                if holder.entity_type in {"office", "region"}:
                    _fail(
                        "invalid_office_holder",
                        "官职持有者必须是人物、势力、机构或临时代理",
                        delta=delta,
                    )
                if holder.status == "ended" or not holder.available:
                    _fail(
                        "inactive_entity_reference",
                        "不能任命已结束或不可用的主体",
                        delta=delta,
                    )
            continue

        if isinstance(delta, LifecycleWorldDelta):
            _validate_lifecycle_goal_delta(
                state,
                delta,
                terminal_death_proposed=terminal_death_proposed,
            )
            continue

        if isinstance(delta, PlayerWorldDelta) and delta.operation == "death":
            if (
                delta.trigger_action != intent.client_action_id
                or not delta.direct_cause
                or not delta.key_factors
                or not delta.causal_summary
                or state.player_world_status.life_status != "alive"
                or delta.before_value != "alive"
                or delta.value != "dead"
                or not set(delta.key_factors).issubset(proposal.key_factors)
            ):
                _fail(
                    "invalid_player_death",
                    "死亡 delta 必须从当前存活状态转为死亡，引用本次行动，并与裁决关键因子一致",
                    delta=delta,
                )
            if proposal.activity_candidate is not None or intent.activity_command is not None:
                _fail(
                    "terminal_activity_unsupported",
                    "终局死亡不得同时创建或继续长期活动",
                    delta=delta,
                )
            if not allow_terminal_death:
                _fail(
                    "terminal_contract_unavailable",
                    "死亡必须由 terminal transaction contract 提交",
                    delta=delta,
                )
            continue

        if isinstance(delta, ModifierWorldDelta) and delta.target_entity_id is not None:
            _require_entity(
                delta.target_entity_id,
                known,
                label="modifier.target_entity_id",
                delta=delta,
            )
        if isinstance(delta, ModifierWorldDelta) and delta.record is not None:
            record_target = delta.record.target.target_entity_id
            if record_target != delta.target_entity_id:
                _fail(
                    "invalid_modifier",
                    "modifier delta target does not match its typed record",
                    delta=delta,
                )

        if isinstance(delta, CommitmentWorldDelta) and delta.record is not None:
            target_entity_id = delta.record.target.target_entity_id
            if target_entity_id is not None:
                _require_entity(
                    target_entity_id,
                    known,
                    label="commitment.target_entity_id",
                    delta=delta,
                )

        if isinstance(delta, ElapsedStatePatchDelta):
            before_keys = set(delta.before_fields)
            after_keys = set(delta.after_fields)
            if (
                not before_keys
                or before_keys != after_keys
                or not before_keys.issubset(ELAPSED_PATCH_FIELDS)
            ):
                _fail(
                    "invalid_elapsed_state_patch",
                    "elapsed handler patch 包含非法或不配对字段",
                    delta=delta,
                )

        if isinstance(delta, CompatibilityStatePatchDelta):
            before_keys = set(delta.before_fields)
            after_keys = set(delta.after_fields)
            if (
                not before_keys
                or before_keys != after_keys
                or not before_keys.issubset(COMPATIBILITY_PATCH_FIELDS)
            ):
                _fail(
                    "invalid_compatibility_state_patch",
                    "legacy action adapter patch 包含非法或不配对字段",
                    delta=delta,
                )


def _assert_before(actual: object, expected: object, delta: WorldDelta) -> None:
    if actual != expected:
        _fail(
            "delta_precondition_failed",
            "delta before_value 与当前世界快照不一致",
            delta=delta,
        )


def _apply_value(actual: object, delta: MetricWorldDelta) -> object:
    _assert_before(actual, delta.before_value, delta)
    if delta.operation == "set":
        return delta.value
    if not _is_number(actual) or not _is_number(delta.value):
        _fail(
            "invalid_delta_value",
            "increment delta 只能应用于数值字段",
            delta=delta,
        )
    return actual + delta.value


def _replace_entity(
    state: GameState,
    entity_id: EntityId,
    entity: WorldEntity,
) -> None:
    state.entity_registry[entity_id] = entity


def _apply_metric_delta(
    state: GameState,
    delta: MetricWorldDelta,
    *,
    executor_facts: ExecutorFacts | None = None,
    roll: RollRecord | None = None,
) -> AppliedMetricAttribution:
    try:
        return apply_typed_metric_delta(
            state,
            delta,
            executor_facts=executor_facts,
            roll=roll,
        )
    except WorldStateValidationError as exc:
        _fail(exc.code, exc.message, delta=delta)
        raise AssertionError("unreachable") from exc


def _apply_entity_delta(state: GameState, delta: EntityWorldDelta) -> None:
    if delta.operation == "create":
        if delta.entity is None or delta.entity.entity_id != delta.target_entity_id:
            _fail(
                "invalid_entity_payload",
                "create delta 缺少 ID 一致的完整主体",
                delta=delta,
            )
        if delta.target_entity_id in state.entity_registry:
            _fail("entity_already_exists", "create delta 的主体 ID 已存在", delta=delta)
        _replace_entity(state, delta.target_entity_id, delta.entity)
        return

    entity = state.entity_registry.get(delta.target_entity_id)
    if entity is None:
        _fail("unknown_entity_reference", "entity delta 的目标不存在", delta=delta)
    if delta.before_status is not None:
        _assert_before(entity.status, delta.before_status, delta)
    payload = entity.model_dump()
    for change in delta.changes:
        if change.field in _PROTECTED_ENTITY_FIELDS:
            _fail(
                "protected_entity_field",
                "主体身份、类型和来源字段不能由普通 update delta 改写",
                delta=delta,
            )
        if change.field in _DEDICATED_REGISTRY_FIELDS:
            _fail(
                "dedicated_registry_delta_required",
                "关系、权限和官职字段必须使用专用 registry delta",
                delta=delta,
            )
        if change.field not in type(entity).model_fields:
            _fail(
                "unsupported_entity_field",
                "entity update 包含未知字段",
                delta=delta,
            )
        _assert_before(getattr(entity, change.field), change.before_value, delta)
        payload[change.field] = change.value
    if delta.operation == "end":
        # Lifecycle state wins even if this function is used without the
        # higher-level proposal validator.
        payload.update({"status": "ended", "available": False})
    try:
        updated = type(entity).model_validate(payload)
    except ValidationError as exc:
        _fail(
            "invalid_entity_payload",
            "entity delta 产生了非法主体状态",
            delta=delta,
        )
        raise AssertionError("unreachable") from exc
    _replace_entity(state, delta.target_entity_id, updated)


def _apply_entity_transition_delta(
    state: GameState,
    delta: EntityTransitionWorldDelta,
) -> None:
    for source in delta.sources:
        entity = state.entity_registry.get(source.entity_id)
        if entity is None:
            _fail(
                "unknown_entity_reference",
                "entity transition 的来源主体不存在",
                delta=delta,
            )
        _assert_before(entity.status, source.status, delta)
    for entity in delta.result_entities:
        if state.entity_registry.get(entity.entity_id) != entity:
            _fail(
                "invalid_entity_transition",
                "entity transition 的结果主体未在批次预登记或内容不一致",
                delta=delta,
            )
    for source in delta.sources:
        entity = state.entity_registry[source.entity_id]
        payload = entity.model_dump()
        payload.update(
            {
                "status": "ended",
                "available": False,
                "ended_at": delta.ended_at or entity.ended_at,
            },
        )
        try:
            ended = type(entity).model_validate(payload)
        except ValidationError as exc:
            _fail(
                "invalid_entity_transition",
                "entity transition 产生了非法来源主体状态",
                delta=delta,
            )
            raise AssertionError("unreachable") from exc
        _replace_entity(state, source.entity_id, ended)


def _stage_registry_entity_results(
    state: GameState,
    deltas: Sequence[WorldDelta],
) -> None:
    """Pre-register same-batch entities without reordering the proposal itself."""

    for delta in deltas:
        if isinstance(delta, EntityWorldDelta) and delta.operation == "create":
            _apply_entity_delta(state, delta)
        elif isinstance(delta, EntityTransitionWorldDelta):
            for entity in delta.result_entities:
                if entity.entity_id in state.entity_registry:
                    _fail(
                        "entity_already_exists",
                        "entity transition 的结果主体 ID 已存在",
                        delta=delta,
                    )
            for entity in delta.result_entities:
                _replace_entity(state, entity.entity_id, entity)


def _apply_relationship_delta(state: GameState, delta: RelationshipWorldDelta) -> None:
    if delta.operation not in {"create", "update", "end"}:
        _fail(
            "unsupported_relationship_operation",
            "权限授予/撤销/任命由后续 registry contract 实现",
            delta=delta,
        )
    source = state.entity_registry.get(delta.from_entity_id)
    if source is None or delta.to_entity_id not in state.entity_registry:
        _fail("unknown_entity_reference", "关系边主体不存在", delta=delta)
    relationships = list(source.relationships)
    matches = _relationship_matches(source, delta)
    if delta.operation == "create":
        if matches:
            _fail("relationship_already_exists", "关系边已存在", delta=delta)
        relationships.append(
            RelationshipEdge(
                relationship_id=_relationship_id(delta),
                relationship_type=delta.relationship_type,
                from_entity_id=delta.from_entity_id,
                to_entity_id=delta.to_entity_id,
                status=delta.next_status or "active",
            ),
        )
    else:
        if len(matches) != 1:
            _fail("relationship_not_found", "关系边不存在或不唯一", delta=delta)
        index, edge = matches[0]
        if delta.before_status is not None:
            _assert_before(edge.status, delta.before_status, delta)
        relationships[index] = edge.model_copy(
            update={"status": "ended" if delta.operation == "end" else delta.next_status},
        )
    payload = source.model_dump()
    payload["relationships"] = relationships
    _replace_entity(state, delta.from_entity_id, type(source).model_validate(payload))


def _apply_permission_delta(state: GameState, delta: PermissionWorldDelta) -> None:
    entity = state.entity_registry.get(delta.target_entity_id)
    if entity is None:
        _fail("unknown_entity_reference", "permission delta 的目标不存在", delta=delta)
    permissions = list(entity.permissions)
    matches = _permission_matches(entity, delta.permission_id)
    if delta.operation == "grant":
        if delta.permission is None:
            _fail("invalid_permission", "grant delta 缺少权限记录", delta=delta)
        if matches:
            _fail("permission_already_exists", "permission_id 已存在", delta=delta)
        permissions.append(delta.permission)
    else:
        if len(matches) != 1:
            _fail("permission_not_found", "permission revoke 的目标不存在", delta=delta)
        index, permission = matches[0]
        _assert_before(permission, delta.before_permission, delta)
        permissions.pop(index)
    payload = entity.model_dump()
    payload["permissions"] = permissions
    try:
        updated = type(entity).model_validate(payload)
    except ValidationError as exc:
        _fail("invalid_permission", "permission delta 产生了非法主体状态", delta=delta)
        raise AssertionError("unreachable") from exc
    _replace_entity(state, delta.target_entity_id, updated)


def _update_person_office(
    state: GameState,
    holder_id: EntityId | None,
    office_id: EntityId,
    *,
    assigned: bool,
    delta: OfficeWorldDelta,
) -> None:
    if holder_id is None:
        return
    holder = state.entity_registry.get(holder_id)
    if not isinstance(holder, PersonEntity):
        return
    office_ids = list(holder.office_ids)
    if assigned:
        if office_id not in office_ids:
            office_ids.append(office_id)
    else:
        office_ids = [candidate for candidate in office_ids if candidate != office_id]
    payload = holder.model_dump()
    payload["office_ids"] = office_ids
    try:
        updated = type(holder).model_validate(payload)
    except ValidationError as exc:
        _fail("invalid_office_assignment", "office delta 产生了非法持有者状态", delta=delta)
        raise AssertionError("unreachable") from exc
    _replace_entity(state, holder_id, updated)


def _apply_office_delta(state: GameState, delta: OfficeWorldDelta) -> None:
    office = state.entity_registry.get(delta.office_entity_id)
    if not isinstance(office, OfficeEntity):
        _fail(
            "invalid_office_reference",
            "office delta 必须引用 OfficeEntity",
            delta=delta,
        )
    _assert_before(
        office.holder_entity_id,
        delta.before_holder_entity_id,
        delta,
    )
    if delta.holder_entity_id is not None and delta.holder_entity_id not in state.entity_registry:
        _fail("unknown_entity_reference", "office holder 不存在", delta=delta)

    _update_person_office(
        state,
        office.holder_entity_id,
        delta.office_entity_id,
        assigned=False,
        delta=delta,
    )
    payload = office.model_dump()
    payload["holder_entity_id"] = delta.holder_entity_id
    try:
        updated_office = type(office).model_validate(payload)
    except ValidationError as exc:
        _fail("invalid_office_assignment", "office delta 产生了非法官职状态", delta=delta)
        raise AssertionError("unreachable") from exc
    _replace_entity(state, delta.office_entity_id, updated_office)
    _update_person_office(
        state,
        delta.holder_entity_id,
        delta.office_entity_id,
        assigned=True,
        delta=delta,
    )


def _apply_player_delta(
    state: GameState,
    delta: PlayerWorldDelta,
    *,
    terminal_ids: tuple[SettlementId, VersionId] | None = None,
) -> None:
    player = state.player_world_status
    if delta.operation == "death":
        if terminal_ids is None:
            _fail(
                "terminal_contract_unavailable",
                "死亡必须由 terminal transaction contract 提交，当前批次不接受提前降级",
                delta=delta,
            )
        _assert_before(player.life_status, delta.before_value, delta)
        if delta.value != "dead":
            _fail("invalid_player_death", "死亡 delta 的目标状态必须为 dead", delta=delta)
        settlement_id, version_id = terminal_ids
        try:
            state.player_world_status = type(player).model_validate(
                player.model_copy(
                    update={
                        "life_status": "dead",
                        "terminal_settlement_id": settlement_id,
                        "terminal_version_id": version_id,
                    },
                ).model_dump(),
            )
        except (ValidationError, ValueError) as exc:
            _fail("invalid_player_death", "死亡 delta 产生了非法终局状态", delta=delta)
            raise AssertionError("unreachable") from exc
        return
    field = {
        "identity": "identity_summary",
        "freedom": "freedom_status",
        "location": "location_entity_id",
        "regime": "regime_status",
    }[delta.operation]
    current = getattr(player, field)
    expected = delta.before_value
    if field == "location_entity_id" and expected is not None:
        expected = EntityId(UUID(expected))
    _assert_before(current, expected, delta)
    value: object = delta.value
    if field == "location_entity_id":
        value = EntityId(UUID(delta.value))
        if value not in state.entity_registry:
            _fail("unknown_entity_reference", "玩家位置主体不存在", delta=delta)
    try:
        state.player_world_status = player.model_copy(update={field: value})
        state.player_world_status = type(player).model_validate(
            state.player_world_status.model_dump(),
        )
    except (ValidationError, ValueError) as exc:
        _fail("invalid_player_delta", "player delta 产生了非法状态", delta=delta)
        raise AssertionError("unreachable") from exc


def _apply_elapsed_state_patch(
    state: GameState,
    delta: ElapsedStatePatchDelta,
) -> GameState:
    keys = set(delta.before_fields)
    if (
        not keys
        or keys != set(delta.after_fields)
        or not keys.issubset(ELAPSED_PATCH_FIELDS)
    ):
        _fail(
            "invalid_elapsed_state_patch",
            "elapsed handler patch 包含非法或不配对字段",
            delta=delta,
        )
    payload = state.model_dump(mode="json")
    for field in sorted(keys):
        if not _patch_field_values_equal(
            field,
            payload[field],
            delta.before_fields[field],
        ):
            _fail(
                "delta_precondition_failed",
                "elapsed handler patch 的 before_fields 与当前世界不一致",
                delta=delta,
            )
        payload[field] = delta.after_fields[field]
    try:
        return GameState.model_validate(payload)
    except ValidationError as exc:
        _fail(
            "invalid_elapsed_state_patch",
            "elapsed handler patch 产生了非法世界状态",
            delta=delta,
        )
        raise AssertionError("unreachable") from exc


def _apply_compatibility_state_patch(
    state: GameState,
    delta: CompatibilityStatePatchDelta,
) -> GameState:
    keys = set(delta.before_fields)
    if (
        not keys
        or keys != set(delta.after_fields)
        or not keys.issubset(COMPATIBILITY_PATCH_FIELDS)
    ):
        _fail(
            "invalid_compatibility_state_patch",
            "legacy action adapter patch 包含非法或不配对字段",
            delta=delta,
        )
    payload = state.model_dump(mode="json")
    for field in sorted(keys):
        if not _patch_field_values_equal(
            field,
            payload[field],
            delta.before_fields[field],
        ):
            _fail(
                "delta_precondition_failed",
                "legacy action adapter patch 的 before_fields 与当前世界不一致",
                delta=delta,
            )
        payload[field] = delta.after_fields[field]
    try:
        return GameState.model_validate(payload)
    except ValidationError as exc:
        _fail(
            "invalid_compatibility_state_patch",
            "legacy action adapter patch 产生了非法世界状态",
            delta=delta,
        )
        raise AssertionError("unreachable") from exc


def _patch_field_values_equal(field: str, left: object, right: object) -> bool:
    """Compare serialized patch values using the field's model semantics."""

    if field in _UNORDERED_PATCH_FIELDS:
        if not isinstance(left, (list, set, tuple)) or not isinstance(
            right,
            (list, set, tuple),
        ):
            return False
        try:
            return set(left) == set(right)
        except TypeError:
            return False
    return left == right


def _apply_world_deltas_with_facts(
    state: GameState,
    deltas: Sequence[WorldDelta],
    *,
    executor_facts: ExecutorFacts | None = None,
    roll: RollRecord | None = None,
    terminal_ids: tuple[SettlementId, VersionId] | None = None,
) -> tuple[GameState, list[AppliedMetricAttribution]]:
    """Apply supported deltas and return the validated snapshot plus attribution."""

    _validate_apply_batch(deltas)
    changed = state.model_copy(deep=True)
    attribution: list[AppliedMetricAttribution] = []
    _stage_registry_entity_results(changed, deltas)
    for delta in deltas:
        if isinstance(delta, MetricWorldDelta):
            attribution.append(
                _apply_metric_delta(
                    changed,
                    delta,
                    executor_facts=executor_facts,
                    roll=roll,
                ),
            )
        elif isinstance(delta, EntityWorldDelta):
            if delta.operation != "create":
                _apply_entity_delta(changed, delta)
        elif isinstance(delta, EntityTransitionWorldDelta):
            _apply_entity_transition_delta(changed, delta)
        elif isinstance(delta, RelationshipWorldDelta):
            _apply_relationship_delta(changed, delta)
        elif isinstance(delta, PermissionWorldDelta):
            _apply_permission_delta(changed, delta)
        elif isinstance(delta, OfficeWorldDelta):
            _apply_office_delta(changed, delta)
        elif isinstance(delta, PlayerWorldDelta):
            _apply_player_delta(changed, delta, terminal_ids=terminal_ids)
        elif isinstance(delta, ElapsedStatePatchDelta):
            changed = _apply_elapsed_state_patch(changed, delta)
        elif isinstance(delta, CompatibilityStatePatchDelta):
            changed = _apply_compatibility_state_patch(changed, delta)
        elif isinstance(delta, ModifierWorldDelta):
            try:
                apply_modifier_delta(changed, delta)
            except WorldStateValidationError as exc:
                _fail(exc.code, exc.message, delta=delta)
        elif isinstance(delta, CommitmentWorldDelta):
            try:
                apply_commitment_delta(changed, delta)
            except WorldStateValidationError as exc:
                _fail(exc.code, exc.message, delta=delta)
        elif isinstance(delta, LifecycleWorldDelta):
            _apply_lifecycle_goal_delta(changed, delta)
        else:
            raise TypeError(f"Unsupported world delta: {type(delta).__name__}")

    try:
        validate_entity_registry(changed.entity_registry)
    except ValueError as exc:
        raise SettlementValidationError(
            "invalid_entity_registry",
            "delta 应用后的主体注册表未通过引用与身份校验",
        ) from exc
    clamp_state(changed)
    try:
        return GameState.model_validate(changed.model_dump()), attribution
    except ValidationError as exc:
        raise SettlementValidationError(
            "invalid_final_state",
            "delta 应用后的世界状态未通过模型校验",
        ) from exc


def apply_world_deltas_with_facts(
    state: GameState,
    deltas: Sequence[WorldDelta],
    *,
    executor_facts: ExecutorFacts | None = None,
    roll: RollRecord | None = None,
) -> tuple[GameState, list[AppliedMetricAttribution]]:
    return _apply_world_deltas_with_facts(
        state,
        deltas,
        executor_facts=executor_facts,
        roll=roll,
    )


def apply_terminal_world_deltas_with_facts(
    state: GameState,
    deltas: Sequence[WorldDelta],
    *,
    settlement_id: SettlementId,
    version_id: VersionId,
    executor_facts: ExecutorFacts | None = None,
    roll: RollRecord | None = None,
) -> tuple[GameState, list[AppliedMetricAttribution]]:
    return _apply_world_deltas_with_facts(
        state,
        deltas,
        executor_facts=executor_facts,
        roll=roll,
        terminal_ids=(settlement_id, version_id),
    )


def apply_world_deltas(
    state: GameState,
    deltas: Sequence[WorldDelta],
    *,
    executor_facts: ExecutorFacts | None = None,
    roll: RollRecord | None = None,
) -> GameState:
    changed, _ = apply_world_deltas_with_facts(
        state,
        deltas,
        executor_facts=executor_facts,
        roll=roll,
    )
    return changed


def validate_final_state(previous: GameState, changed: GameState) -> None:
    if changed.world_metadata != previous.world_metadata:
        raise SettlementValidationError(
            "world_identity_mutation",
            "delta application 不得改写当前世界版本身份",
        )
    if not set(previous.entity_registry).issubset(changed.entity_registry):
        raise SettlementValidationError(
            "entity_registry_regression",
            "delta application 不得删除已登记主体；结束主体必须保留身份与历史",
        )
    previous_player_id = previous.player_world_status.player_character_id
    if (
        previous_player_id is not None
        and changed.player_world_status.player_character_id != previous_player_id
    ):
        raise SettlementValidationError(
            "player_identity_regression",
            "delta application 不得替换或清空稳定玩家主体身份",
        )
    try:
        validate_entity_registry(changed.entity_registry)
    except ValueError as exc:
        raise SettlementValidationError(
            "invalid_entity_registry",
            "delta application 产生了非法主体引用、权限、关系或官职状态",
        ) from exc
    if changed.model_dump(mode="json") == previous.model_dump(mode="json"):
        raise SettlementValidationError(
            "no_state_change",
            "no-op 裁决不得创建空 settlement/version",
        )
