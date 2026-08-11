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
    EntityWorldDelta,
    LifecycleWorldDelta,
    MetricWorldDelta,
    ModifierWorldDelta,
    PlayerWorldDelta,
    RelationshipWorldDelta,
    WorldDelta,
)
from models.world import EntityId, RelationId, RelationshipEdge, WorldEntity


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
    raise TypeError(f"Unsupported world delta: {type(delta).__name__}")


def validate_adjudication_proposal(
    intent: ActionIntent,
    state: GameState,
    proposal: AdjudicationProposal,
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
    ):
        if reference is not None:
            _require_entity(reference, known, label=label)
    for entity_id in intent.target_entity_ids:
        _require_entity(entity_id, known, label="target_entity_ids")

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
            ):
                _fail(
                    "invalid_player_death",
                    "死亡 delta 必须引用本次行动并包含死因、关键因子和因果摘要",
                    delta=delta,
                )
            _fail(
                "terminal_contract_unavailable",
                "死亡必须等待 terminal transaction contract，不得提前提交",
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


def _apply_metric_delta(state: GameState, delta: MetricWorldDelta) -> None:
    if delta.target_scope == "world":
        if delta.field not in _WORLD_METRIC_FIELDS:
            _fail(
                "unsupported_metric_field",
                "该世界字段不允许通过 metric delta 修改",
                delta=delta,
            )
        current = getattr(state, delta.field)
        setattr(state, delta.field, _apply_value(current, delta))
        return

    if delta.target_id is None or delta.target_id not in state.entity_registry:
        _fail(
            "unknown_entity_reference",
            "metric delta 的目标主体不存在",
            delta=delta,
        )
    entity = state.entity_registry[delta.target_id]
    if delta.target_scope == "region" and entity.entity_type != "region":
        _fail(
            "invalid_delta_target",
            "region metric delta 必须引用地区主体",
            delta=delta,
        )
    if delta.field not in type(entity).model_fields:
        _fail(
            "unsupported_metric_field",
            "目标主体不存在该 metric 字段",
            delta=delta,
        )
    current = getattr(entity, delta.field)
    payload = entity.model_dump()
    payload[delta.field] = _apply_value(current, delta)
    try:
        updated = type(entity).model_validate(payload)
    except ValidationError as exc:
        _fail(
            "invalid_delta_value",
            "metric delta 产生了非法主体状态",
            delta=delta,
        )
        raise AssertionError("unreachable") from exc
    _replace_entity(state, delta.target_id, updated)


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


def _apply_player_delta(state: GameState, delta: PlayerWorldDelta) -> None:
    player = state.player_world_status
    if delta.operation == "death":
        _fail(
            "terminal_contract_unavailable",
            "死亡必须由 terminal transaction contract 提交，当前批次不接受提前降级",
            delta=delta,
        )
    field = {
        "identity": "identity_summary",
        "freedom": "freedom_status",
        "location": "location_entity_id",
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


def apply_world_deltas(
    state: GameState,
    deltas: Sequence[WorldDelta],
) -> GameState:
    """Apply supported deltas to a deep copy and return a validated snapshot."""

    changed = state.model_copy(deep=True)
    for delta in deltas:
        if isinstance(delta, MetricWorldDelta):
            _apply_metric_delta(changed, delta)
        elif isinstance(delta, EntityWorldDelta):
            _apply_entity_delta(changed, delta)
        elif isinstance(delta, RelationshipWorldDelta):
            _apply_relationship_delta(changed, delta)
        elif isinstance(delta, PlayerWorldDelta):
            _apply_player_delta(changed, delta)
        elif isinstance(delta, (LifecycleWorldDelta, ModifierWorldDelta)):
            _fail(
                "sibling_contract_unavailable",
                "该 delta 必须等待对应 sibling contract，不得由 sandbox 重实现",
                delta=delta,
            )
        else:
            raise TypeError(f"Unsupported world delta: {type(delta).__name__}")

    clamp_state(changed)
    try:
        return GameState.model_validate(changed.model_dump())
    except ValidationError as exc:
        raise SettlementValidationError(
            "invalid_final_state",
            "delta 应用后的世界状态未通过模型校验",
        ) from exc


def validate_final_state(previous: GameState, changed: GameState) -> None:
    if changed.world_metadata != previous.world_metadata:
        raise SettlementValidationError(
            "world_identity_mutation",
            "delta application 不得改写当前世界版本身份",
        )
    if changed.model_dump(mode="json") == previous.model_dump(mode="json"):
        raise SettlementValidationError(
            "no_state_change",
            "no-op 裁决不得创建空 settlement/version",
        )
