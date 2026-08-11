"""Pure deterministic application and projection for world-state-owned facts."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, ROUND_DOWN
from numbers import Real

from models.game import GameState
from models.settlement import CommitmentWorldDelta, MetricWorldDelta, ModifierWorldDelta
from models.world import RegionEntity, WorldInstant
from models.world_state import (
    AppliedMetricAttribution,
    CommitmentRecord,
    ExecutorFacts,
    MetricProjection,
    MetricSpec,
    MetricTarget,
    ModifierRecord,
    RegionProjection,
    RollRecord,
    WorldStateProjection,
)


class WorldStateValidationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


WORLD_METRIC_SPECS: dict[str, MetricSpec] = {
    "national_treasury": MetricSpec(target_scope="world", metric_key="national_treasury", numeric_kind="integer", minimum=0, maximum=10000),
    "imperial_treasury": MetricSpec(target_scope="world", metric_key="imperial_treasury", numeric_kind="integer", minimum=0, maximum=10000),
    "grain": MetricSpec(target_scope="world", metric_key="grain", numeric_kind="integer", minimum=0, maximum=50000),
    "population": MetricSpec(target_scope="world", metric_key="population", numeric_kind="integer", minimum=0, maximum=20000),
    "military_strength": MetricSpec(target_scope="world", metric_key="military_strength", numeric_kind="integer", minimum=0, maximum=2000),
    "civil_morale": MetricSpec(target_scope="world", metric_key="civil_morale", numeric_kind="integer", minimum=0, maximum=100),
    "military_morale": MetricSpec(target_scope="world", metric_key="military_morale", numeric_kind="integer", minimum=0, maximum=100),
    "court_prestige": MetricSpec(target_scope="world", metric_key="court_prestige", numeric_kind="integer", minimum=0, maximum=100),
    "chapter_turns": MetricSpec(target_scope="world", metric_key="chapter_turns", numeric_kind="integer", minimum=0),
    "decree_count": MetricSpec(target_scope="world", metric_key="decree_count", numeric_kind="integer", minimum=0),
    "consecutive_waits": MetricSpec(target_scope="world", metric_key="consecutive_waits", numeric_kind="integer", minimum=0),
}


def _decimal(value: object, *, code: str = "invalid_delta_value") -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise WorldStateValidationError(code, "metric value must be a finite number")
    result = Decimal(str(value))
    if not result.is_finite():
        raise WorldStateValidationError(code, "metric value must be finite")
    return result


def _public_number(value: Decimal, spec: MetricSpec) -> int | float:
    if spec.numeric_kind == "integer":
        return int(value)
    return float(value)


def _quantize(value: Decimal, spec: MetricSpec) -> Decimal:
    quantum = Decimal(1).scaleb(-spec.precision)
    return value.quantize(quantum, rounding=ROUND_DOWN)


def _clamp(value: Decimal, spec: MetricSpec) -> Decimal:
    if spec.minimum is not None:
        value = max(value, spec.minimum)
    if spec.maximum is not None:
        value = min(value, spec.maximum)
    return value


def _metric_spec(delta: MetricWorldDelta) -> MetricSpec:
    if delta.target_scope != "world":
        raise WorldStateValidationError(
            "unsupported_metric_field",
            "dynamic entity metrics require a registered typed MetricSpec",
        )
    spec = WORLD_METRIC_SPECS.get(delta.field)
    if spec is None:
        raise WorldStateValidationError(
            "unsupported_metric_field",
            "world metric is not registered in the central MetricSpec registry",
        )
    return spec


def apply_metric_delta(
    state: GameState,
    delta: MetricWorldDelta,
    *,
    executor_facts: ExecutorFacts | None = None,
    roll: RollRecord | None = None,
) -> AppliedMetricAttribution:
    """Apply one numeric delta once, with deterministic precision and clamp."""

    spec = _metric_spec(delta)
    before = _decimal(getattr(state, delta.field))
    expected = _decimal(delta.before_value)
    if before != expected:
        raise WorldStateValidationError(
            "delta_precondition_failed",
            "delta before_value does not match the current metric",
        )
    proposed = _decimal(delta.value)
    if delta.operation == "set":
        raw_after = proposed
        proposed_delta = proposed - before
        executor_adjustment = Decimal(0)
    else:
        proposed_delta = proposed
        adjusted_delta = proposed_delta
        if executor_facts is not None and executor_facts.actual_executor_id is not None:
            adjusted_delta *= executor_facts.efficiency
        executor_adjustment = adjusted_delta - proposed_delta
        raw_after = before + adjusted_delta

    precise_after = _quantize(raw_after, spec)
    precision_adjustment = precise_after - raw_after
    clamped_after = _clamp(precise_after, spec)
    clamp_adjustment = clamped_after - precise_after
    setattr(state, delta.field, _public_number(clamped_after, spec))
    actual_delta = clamped_after - before
    return AppliedMetricAttribution(
        delta_id=str(delta.delta_id),
        target=MetricTarget(target_scope=delta.target_scope, metric_key=delta.field),
        before_value=_public_number(before, spec),
        proposed_value=_public_number(proposed_delta, spec),
        executor_adjustment=_public_number(executor_adjustment, spec),
        precision_adjustment=_public_number(precision_adjustment, spec),
        clamp_adjustment=_public_number(clamp_adjustment, spec),
        actual_delta=_public_number(actual_delta, spec),
        after_value=_public_number(clamped_after, spec),
        executor_facts=executor_facts,
        roll_id=roll.roll_id if roll is not None else None,
    )


def _current_instant(state: GameState) -> WorldInstant:
    clock = state.time.clock
    if clock is None:
        raise WorldStateValidationError("invalid_time_contract", "modifier operations require a canonical world clock")
    return WorldInstant.model_validate(clock.model_dump())


def _validate_modifier_end(record: ModifierRecord, ended_at: WorldInstant) -> None:
    started_at = record.started_at
    if (
        started_at.calendar_version != ended_at.calendar_version
        or started_at.epoch_id != ended_at.epoch_id
        or started_at.world_timezone != ended_at.world_timezone
    ):
        raise WorldStateValidationError(
            "invalid_time_contract",
            "modifier end clock identity does not match started_at",
        )
    if ended_at.absolute_hour < started_at.absolute_hour:
        raise WorldStateValidationError(
            "delta_precondition_failed",
            "modifier cannot end before started_at",
        )


def apply_modifier_delta(state: GameState, delta: ModifierWorldDelta) -> None:
    records = state.world_state.modifiers
    existing = records.get(delta.modifier_id)
    if delta.operation == "create":
        if existing is not None or delta.record is None:
            raise WorldStateValidationError("invalid_modifier", "create requires one new typed modifier record")
        if delta.record.modifier_id != delta.modifier_id:
            raise WorldStateValidationError("invalid_modifier", "modifier id does not match its delta")
        conflicts = [
            record
            for record in records.values()
            if record.status == "active"
            and record.target == delta.record.target
            and record.stacking_group == delta.record.stacking_group
        ]
        if delta.record.stacking_policy == "exclusive" and conflicts:
            raise WorldStateValidationError("modifier_conflict", "exclusive modifier group already has an active record")
        if delta.record.stacking_policy == "replace":
            now = _current_instant(state)
            for record in conflicts:
                _validate_modifier_end(record, now)
                records[record.modifier_id] = record.model_copy(update={"status": "ended", "ended_at": now})
        records[delta.modifier_id] = delta.record
        return
    if existing is None:
        raise WorldStateValidationError("modifier_not_found", "modifier update/end target does not exist")
    if delta.before_status is not None and existing.status != delta.before_status:
        raise WorldStateValidationError("delta_precondition_failed", "modifier status does not match before_status")
    if delta.operation == "update":
        if delta.record is None or delta.record.modifier_id != delta.modifier_id:
            raise WorldStateValidationError("invalid_modifier", "update requires a matching typed modifier record")
        records[delta.modifier_id] = delta.record
        return
    if existing.status != "active":
        raise WorldStateValidationError(
            "delta_precondition_failed",
            "only an active modifier can be ended",
        )
    if delta.record is not None or delta.ended_at is None:
        raise WorldStateValidationError("invalid_modifier", "end modifier delta requires ended_at only")
    _validate_modifier_end(existing, delta.ended_at)
    records[delta.modifier_id] = existing.model_copy(
        update={"status": "ended", "ended_at": delta.ended_at},
    )


def _validate_commitment_record(record: CommitmentRecord) -> None:
    target = record.target
    if target.target_scope != "world" or target.target_entity_id is not None:
        raise WorldStateValidationError(
            "unsupported_metric_field",
            "commitments currently require a registered world metric target",
        )
    spec = WORLD_METRIC_SPECS.get(target.metric_key)
    if spec is None:
        raise WorldStateValidationError(
            "unsupported_metric_field",
            "commitment metric is not registered in the central MetricSpec registry",
        )
    if spec.numeric_kind == "integer" and record.amount != record.amount.to_integral_value():
        raise WorldStateValidationError(
            "invalid_delta_value",
            "integer metric commitments require an integral amount",
        )


def apply_commitment_delta(state: GameState, delta: CommitmentWorldDelta) -> None:
    records = state.world_state.commitments
    existing = records.get(delta.commitment_id)
    if delta.operation == "create":
        if existing is not None or delta.record is None or delta.record.status != "pending":
            raise WorldStateValidationError(
                "invalid_commitment",
                "create requires one new pending typed commitment record",
            )
        _validate_commitment_record(delta.record)
        records[delta.commitment_id] = delta.record
        return
    if existing is None:
        raise WorldStateValidationError(
            "commitment_not_found",
            "commitment update/transition target does not exist",
        )
    if delta.before_status is not None and existing.status != delta.before_status:
        raise WorldStateValidationError(
            "delta_precondition_failed",
            "commitment status does not match before_status",
        )
    if delta.operation == "update":
        if (
            existing.status != "pending"
            or delta.record is None
            or delta.record.status != "pending"
        ):
            raise WorldStateValidationError(
                "invalid_commitment",
                "only a pending commitment can be updated with a pending record",
            )
        _validate_commitment_record(delta.record)
        records[delta.commitment_id] = delta.record
        return
    if existing.status != "pending" or delta.transitioned_at is None:
        raise WorldStateValidationError(
            "delta_precondition_failed",
            "only a pending commitment can transition",
        )
    due = existing.due_at
    transitioned_at = delta.transitioned_at
    if (
        due.calendar_version != transitioned_at.calendar_version
        or due.epoch_id != transitioned_at.epoch_id
        or due.world_timezone != transitioned_at.world_timezone
    ):
        raise WorldStateValidationError(
            "invalid_time_contract",
            "commitment transition clock identity does not match due_at",
        )
    if delta.operation == "apply" and transitioned_at.absolute_hour < due.absolute_hour:
        raise WorldStateValidationError(
            "delta_precondition_failed",
            "commitment cannot be applied before due_at",
        )
    next_status = {
        "apply": "applied",
        "cancel": "cancelled",
        "fail": "failed",
    }[delta.operation]
    records[delta.commitment_id] = existing.model_copy(update={"status": next_status})


def active_modifiers(state: GameState, target: MetricTarget) -> list[ModifierRecord]:
    records = [
        record
        for record in state.world_state.modifiers.values()
        if record.status == "active"
        and record.target == target
    ]
    if state.time.clock is None and any(record.ends_at is not None for record in records):
        raise WorldStateValidationError(
            "invalid_time_contract",
            "timed modifier projection requires a canonical world clock",
        )
    now = state.time.clock.absolute_hour if state.time.clock is not None else None
    records = [
        record
        for record in records
        if record.ends_at is None or record.ends_at.absolute_hour > now
    ]
    return sorted(records, key=lambda record: (record.priority, record.modifier_id))


def _effective_value(base: Decimal, records: Iterable[ModifierRecord]) -> Decimal:
    records = list(records)
    value = base + sum(
        (record.transform.amount or Decimal(0))
        for record in records
        if record.transform.kind == "add"
    )
    for record in records:
        transform = record.transform
        if transform.kind == "multiply":
            value *= Decimal(transform.numerator) / Decimal(transform.denominator)
    for record in records:
        transform = record.transform
        if transform.kind == "minimum":
            value = max(value, transform.amount)
        elif transform.kind == "maximum":
            value = min(value, transform.amount)
    return value


def metric_projection(
    state: GameState,
    metric_key: str,
    *,
    recent_sources: Iterable[AppliedMetricAttribution] = (),
) -> MetricProjection:
    spec = WORLD_METRIC_SPECS.get(metric_key)
    if spec is None:
        raise WorldStateValidationError("unsupported_metric_field", "metric is not registered")
    target = MetricTarget(target_scope="world", metric_key=metric_key)
    base = _decimal(getattr(state, metric_key))
    modifiers = active_modifiers(state, target)
    effective = _clamp(_quantize(_effective_value(base, modifiers), spec), spec)
    from engine.numeric_bands import band_of
    from engine.tables import GLOBAL_BANDS

    base_band = band_of(GLOBAL_BANDS.get(metric_key), base)
    effective_band = band_of(GLOBAL_BANDS.get(metric_key), effective)
    commitments = [
        commitment
        for commitment in state.world_state.commitments.values()
        if commitment.target == target and commitment.status == "pending"
    ]
    matching_sources = [
        source
        for source in recent_sources
        if source.target == target
    ]
    return MetricProjection(
        version_id=state.world_metadata.version_id,
        target=target,
        base_value=_public_number(base, spec),
        base_band=base_band[0] if base_band else None,
        active_modifiers=modifiers,
        effective_value=_public_number(effective, spec),
        effective_band=effective_band[0] if effective_band else None,
        recent_sources=matching_sources,
        commitments=sorted(commitments, key=lambda item: item.commitment_id),
    )


def project_effective_state(state: GameState) -> GameState:
    projected = state.model_copy(deep=True)
    for metric_key in WORLD_METRIC_SPECS:
        projection = metric_projection(state, metric_key)
        setattr(projected, metric_key, projection.effective_value)
    return projected


def world_state_projection(
    state: GameState,
    *,
    recent_sources: Iterable[AppliedMetricAttribution] = (),
) -> WorldStateProjection:
    from engine.execution import executor_candidates

    recent_sources = list(recent_sources)
    regions = [
        RegionProjection(
            version_id=state.world_metadata.version_id,
            region_id=entity_id,
            display_name=entity.display_name,
            controller_entity_id=entity.controller_entity_id,
        )
        for entity_id, entity in sorted(state.entity_registry.items(), key=lambda item: str(item[0]))
        if isinstance(entity, RegionEntity)
    ]
    return WorldStateProjection(
        version_id=state.world_metadata.version_id,
        metrics=[
            metric_projection(state, key, recent_sources=recent_sources)
            for key in WORLD_METRIC_SPECS
        ],
        executors=executor_candidates(state),
        regions=regions,
    )
