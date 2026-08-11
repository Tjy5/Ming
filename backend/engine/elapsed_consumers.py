"""Registered elapsed-time adapters owned outside the clock planner."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from models.game import GameState
from models.settlement import (
    CommitmentWorldDelta,
    ElapsedStatePatchDelta,
    MetricWorldDelta,
    ModifierWorldDelta,
    WorldDelta,
)
from models.world import (
    BoundaryKind,
    ClockConsumerInvocation,
    DeltaId,
    ElapsedSegment,
    TimeBoundary,
    WorldInstant,
)

from .calendar import set_game_time_projection
from .clock import ClockConsumerRegistry
from .core import apply_elapsed_month_boundary, expire_events, inject_script_events
from .settlement import ELAPSED_PATCH_FIELDS, apply_world_deltas
from .world_state import WORLD_METRIC_SPECS


class LegacyMonthlyWorldStateConsumer:
    """Compatibility adapter for existing monthly gameplay calculations.

    It computes on a copy and returns one typed patch. It never advances the
    canonical clock, touches SQLite, or creates a settlement/version.
    """

    name = "legacy-world-state-monthly"
    version = "1"
    order = 100
    boundary_kinds: frozenset[BoundaryKind] = frozenset({"month"})

    def __init__(
        self,
        script_trigger_decisions: dict[str, tuple[bool, str]] | None = None,
    ) -> None:
        self._script_trigger_decisions = script_trigger_decisions

    def consume(
        self,
        *,
        state: GameState,
        segment: ElapsedSegment,
        boundary: TimeBoundary,
        invocation: ClockConsumerInvocation,
    ) -> list[WorldDelta]:
        modifier_deltas: list[WorldDelta] = [
            ModifierWorldDelta(
                delta_id=DeltaId(
                    uuid5(
                        NAMESPACE_URL,
                        f"modifier-expiry:{invocation.invocation_id}:{record.modifier_id}",
                    ),
                ),
                operation="end",
                modifier_id=record.modifier_id,
                target_entity_id=record.target.target_entity_id,
                before_status="active",
                ended_at=record.ends_at,
                source_proposal=f"elapsed:{boundary.boundary_key}",
            )
            for record in sorted(
                state.world_state.modifiers.values(),
                key=lambda item: item.modifier_id,
            )
            if record.status == "active"
            and record.ends_at is not None
            and segment.start.absolute_hour < record.ends_at.absolute_hour <= boundary.absolute_hour
        ]
        before_values = state.model_dump(mode="python")
        before = state.model_dump(mode="json")
        projected = project_state_at_boundary(state, boundary)
        apply_elapsed_month_boundary(projected)
        inject_script_events(
            projected,
            script_trigger_decisions=self._script_trigger_decisions,
        )
        expire_events(projected)
        after_values = projected.model_dump(mode="python")
        after = projected.model_dump(mode="json")

        changed_fields = [
            field
            for field in sorted(ELAPSED_PATCH_FIELDS)
            if before_values[field] != after_values[field]
        ]
        if not changed_fields:
            return modifier_deltas
        return [
            *modifier_deltas,
            ElapsedStatePatchDelta(
                delta_id=DeltaId(
                    uuid5(NAMESPACE_URL, f"clock-consumer:{invocation.invocation_id}"),
                ),
                handler_name=self.name,
                handler_version=self.version,
                boundary_id=boundary.boundary_id,
                before_fields={field: before[field] for field in changed_fields},
                after_fields={field: after[field] for field in changed_fields},
                source_proposal=f"elapsed:{boundary.boundary_key}",
            ),
        ]


class WorldStateDueConsumer:
    """Settle timed modifiers and persisted commitments at every action end."""

    name = "world-state-due"
    version = "1"
    order = 200
    boundary_kinds: frozenset[BoundaryKind] = frozenset({"end"})

    def consume(
        self,
        *,
        state: GameState,
        segment: ElapsedSegment,
        boundary: TimeBoundary,
        invocation: ClockConsumerInvocation,
    ) -> list[WorldDelta]:
        del segment
        transitioned_at = WorldInstant(
            absolute_hour=boundary.absolute_hour,
            calendar_version=boundary.calendar_version,
            epoch_id=boundary.epoch_id,
            world_timezone=boundary.world_timezone,
        )
        deltas: list[WorldDelta] = []
        for record in sorted(
            state.world_state.modifiers.values(),
            key=lambda item: item.modifier_id,
        ):
            if (
                record.status == "active"
                and record.ends_at is not None
                and record.ends_at.absolute_hour <= boundary.absolute_hour
            ):
                deltas.append(
                    ModifierWorldDelta(
                        delta_id=DeltaId(
                            uuid5(
                                NAMESPACE_URL,
                                f"modifier-expiry:{invocation.invocation_id}:{record.modifier_id}",
                            ),
                        ),
                        operation="end",
                        modifier_id=record.modifier_id,
                        target_entity_id=record.target.target_entity_id,
                        before_status="active",
                        ended_at=record.ends_at,
                        source_proposal=f"elapsed:{boundary.boundary_key}",
                    ),
                )

        due_commitments = [
            record
            for record in state.world_state.commitments.values()
            if record.status == "pending"
            and record.due_at.absolute_hour <= boundary.absolute_hour
        ]
        if any(
            record.target.target_scope != "world"
            or record.target.target_entity_id is not None
            or record.target.metric_key not in WORLD_METRIC_SPECS
            for record in due_commitments
        ):
            raise ValueError("pending commitment target is not a registered world metric")
        projected = state.model_copy(deep=True)
        for record in sorted(
            due_commitments,
            key=lambda item: item.commitment_id,
        ):
            metric_key = record.target.metric_key
            before_value = getattr(projected, metric_key)
            amount = (
                int(record.amount)
                if record.amount == record.amount.to_integral_value()
                else float(record.amount)
            )
            commitment_deltas: list[WorldDelta] = [
                    MetricWorldDelta(
                        delta_id=DeltaId(
                            uuid5(
                                NAMESPACE_URL,
                                f"commitment-metric:{invocation.invocation_id}:{record.commitment_id}",
                            ),
                        ),
                        target_scope="world",
                        field=metric_key,
                        operation="increment",
                        before_value=before_value,
                        value=amount,
                        source_proposal=f"commitment:{record.commitment_id}",
                    ),
                    CommitmentWorldDelta(
                        delta_id=DeltaId(
                            uuid5(
                                NAMESPACE_URL,
                                f"commitment-apply:{invocation.invocation_id}:{record.commitment_id}",
                            ),
                        ),
                        operation="apply",
                        commitment_id=record.commitment_id,
                        before_status="pending",
                        transitioned_at=transitioned_at,
                        source_proposal=f"elapsed:{boundary.boundary_key}",
                    ),
                ]
            projected = apply_world_deltas(projected, commitment_deltas)
            deltas.extend(commitment_deltas)
        return deltas


def project_state_at_boundary(state: GameState, boundary: TimeBoundary) -> GameState:
    """Build a disposable boundary projection for AI/consumer evaluation."""
    projected = state.model_copy(deep=True)
    calendar = boundary.projection
    set_game_time_projection(
        projected.time,
        year=calendar.year,
        month=calendar.month,
        day=calendar.day,
        hour=calendar.hour,
        is_leap_month=calendar.is_leap_month,
        calendar_version=calendar.calendar_version,
        migration_source=projected.time.time_migration_source,
    )
    return projected


def default_clock_registry(
    script_trigger_decisions: dict[str, tuple[bool, str]] | None = None,
) -> ClockConsumerRegistry:
    return ClockConsumerRegistry(
        [
            LegacyMonthlyWorldStateConsumer(script_trigger_decisions),
            WorldStateDueConsumer(),
        ],
    )
