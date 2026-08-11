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
    EntityWorldDelta,
    LifecycleWorldDelta,
    MetricWorldDelta,
    ModifierWorldDelta,
    PlayerWorldDelta,
    RelationshipWorldDelta,
    WorldDelta,
)
from models.world import (
    EntityId,
    RelationId,
    RelationshipEdge,
    SettlementId,
    VersionId,
    WorldEntity,
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
    return known


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
    delta: EntityWorldDelta,
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


def _delta_conflict_key(delta: WorldDelta) -> Hashable:
    if isinstance(delta, MetricWorldDelta):
        return ("metric", delta.target_scope, delta.target_id, delta.field)
    if isinstance(delta, EntityWorldDelta):
        return ("entity", delta.target_entity_id)
    if isinstance(delta, RelationshipWorldDelta):
        return (
            "relationship",
            delta.from_entity_id,
            delta.to_entity_id,
            delta.relationship_type,
        )
    if isinstance(delta, LifecycleWorldDelta):
        return ("lifecycle", delta.transition_type, delta.transition_id)
    if isinstance(delta, PlayerWorldDelta):
        return ("player", delta.operation)
    if isinstance(delta, ModifierWorldDelta):
        return ("modifier", delta.modifier_id)
    if isinstance(delta, CommitmentWorldDelta):
        return ("commitment", delta.commitment_id)
    if isinstance(delta, ElapsedStatePatchDelta):
        return ("elapsed_state_patch", tuple(sorted(delta.after_fields)))
    if isinstance(delta, CompatibilityStatePatchDelta):
        return ("compatibility_state_patch", tuple(sorted(delta.after_fields)))
    raise TypeError(f"Unsupported world delta: {type(delta).__name__}")


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

        conflict_key = _delta_conflict_key(delta)
        if conflict_key in seen_conflicts:
            _fail(
                "delta_conflict",
                "同一裁决批次对同一目标给出了冲突变化",
                delta=delta,
            )
        seen_conflicts.add(conflict_key)

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
                _validate_entity_payload_references(delta.entity, known, delta)
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
                if delta.operation == "end" and change.field in {"status", "available"}:
                    _fail(
                        "invalid_entity_end",
                        "end delta 不得通过 changes 恢复主体状态或可用性",
                        delta=delta,
                    )
                change_fields.add(change.field)
            continue

        if isinstance(delta, RelationshipWorldDelta):
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
        if delta.entity is None:
            _fail("invalid_entity_payload", "create delta 缺少主体", delta=delta)
        _replace_entity(state, delta.target_entity_id, delta.entity)
        return

    entity = state.entity_registry.get(delta.target_entity_id)
    if entity is None:
        _fail("unknown_entity_reference", "entity delta 的目标不存在", delta=delta)
    if delta.before_status is not None:
        _assert_before(entity.status, delta.before_status, delta)
    payload = entity.model_dump()
    for change in delta.changes:
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
    matches = [
        (index, edge)
        for index, edge in enumerate(relationships)
        if edge.to_entity_id == delta.to_entity_id
        and edge.relationship_type == delta.relationship_type
    ]
    if delta.operation == "create":
        if matches:
            _fail("relationship_already_exists", "关系边已存在", delta=delta)
        relationships.append(
            RelationshipEdge(
                relationship_id=RelationId(UUID(str(delta.delta_id))),
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

    changed = state.model_copy(deep=True)
    attribution: list[AppliedMetricAttribution] = []
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
            _apply_entity_delta(changed, delta)
        elif isinstance(delta, RelationshipWorldDelta):
            _apply_relationship_delta(changed, delta)
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
            _fail(
                "sibling_contract_unavailable",
                "该 delta 必须等待对应 sibling contract，不得由 sandbox 重实现",
                delta=delta,
            )
        else:
            raise TypeError(f"Unsupported world delta: {type(delta).__name__}")

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
    if changed.model_dump(mode="json") == previous.model_dump(mode="json"):
        raise SettlementValidationError(
            "no_state_change",
            "no-op 裁决不得创建空 settlement/version",
        )
