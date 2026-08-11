"""Registered elapsed-time adapters owned outside the clock planner."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from models.game import GameState
from models.settlement import ElapsedStatePatchDelta, WorldDelta
from models.world import (
    BoundaryKind,
    ClockConsumerInvocation,
    DeltaId,
    ElapsedSegment,
    TimeBoundary,
)

from .calendar import set_game_time_projection
from .clock import ClockConsumerRegistry
from .core import apply_elapsed_month_boundary, expire_events, inject_script_events
from .settlement import ELAPSED_PATCH_FIELDS


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
        del segment
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
            return []
        return [
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
        [LegacyMonthlyWorldStateConsumer(script_trigger_decisions)],
    )
