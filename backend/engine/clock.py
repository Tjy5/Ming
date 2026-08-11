"""Deterministic elapsed-time planning and clock-consumer dispatch.

This module owns duration normalization, crossed-boundary facts, and stable
consumer ordering. Gameplay effects remain in registered consumers and are
returned as typed world deltas; no drift, policy, modifier, or commitment math
belongs here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from models.game import GameState
from models.settlement import WorldDelta
from models.world import (
    BoundaryKind,
    ClientActionId,
    ClockConsumerInvocation,
    Duration,
    ElapsedSegment,
    ElapsedSegmentPlan,
    TimeBoundary,
    WorldInstant,
)

from .calendar import (
    CalendarError,
    normalize_duration,
    projection_from_absolute_hour,
)


MAX_BOUNDARIES_PER_SEGMENT = 512

_BOUNDARY_ORDER: dict[BoundaryKind, int] = {
    "day": 10,
    "month": 20,
    "year": 30,
    "solar_term": 40,
    "end": 90,
}
_WORLD_DELTA_LIST_ADAPTER = TypeAdapter(list[WorldDelta])


class ClockPlanningError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class ClockConsumer(Protocol):
    name: str
    version: str
    order: int
    boundary_kinds: frozenset[BoundaryKind]

    def consume(
        self,
        *,
        state: GameState,
        segment: ElapsedSegment,
        boundary: TimeBoundary,
        invocation: ClockConsumerInvocation,
    ) -> Sequence[WorldDelta]: ...


def _stable_id(*parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _boundary_key(kind: BoundaryKind, projection, absolute_hour: int) -> str:
    leap = "leap" if projection.is_leap_month else "regular"
    if kind == "day":
        return f"day:{projection.year}:{projection.month}:{leap}:{projection.day}"
    if kind == "month":
        return f"month:{projection.year}:{projection.month}:{leap}"
    if kind == "year":
        return f"year:{projection.year}"
    if kind == "solar_term":
        return (
            f"solar_term:{projection.year}:{projection.month}:{leap}:"
            f"{projection.solar_term}"
        )
    return f"end:{absolute_hour}"


def _make_boundary(
    segment_id: str,
    kind: BoundaryKind,
    absolute_hour: int,
    *,
    calendar_version: str,
    epoch_id: str,
    world_timezone: str,
) -> TimeBoundary:
    projection = projection_from_absolute_hour(
        absolute_hour,
        calendar_version=calendar_version,
    )
    boundary_key = _boundary_key(kind, projection, absolute_hour)
    return TimeBoundary(
        boundary_id=_stable_id(
            segment_id,
            absolute_hour,
            kind,
            boundary_key,
            calendar_version,
        ),
        kind=kind,
        boundary_key=boundary_key,
        absolute_hour=absolute_hour,
        calendar_version=calendar_version,
        epoch_id=epoch_id,
        world_timezone=world_timezone,
        projection=projection,
    )


def enumerate_boundaries(
    segment: ElapsedSegment,
    *,
    max_boundaries: int = MAX_BOUNDARIES_PER_SEGMENT,
) -> tuple[TimeBoundary, ...]:
    """Enumerate deterministic calendar facts in ``(start, end]``."""

    if (
        isinstance(max_boundaries, bool)
        or not isinstance(max_boundaries, int)
        or max_boundaries <= 0
    ):
        raise ClockPlanningError(
            "invalid_boundary_limit",
            "max_boundaries must be a positive integer",
        )

    start_hour = segment.start.absolute_hour
    end_hour = segment.end.absolute_hour
    first_day_index = start_hour // 24 + 1
    last_day_index = end_hour // 24
    crossed_day_count = max(0, last_day_index - first_day_index + 1)
    if crossed_day_count + 1 > max_boundaries:
        raise ClockPlanningError(
            "activity_contract_required",
            "行动跨越的时间边界过多，必须由有界 activity/checkpoint contract 处理",
        )

    candidates: list[TimeBoundary] = []

    def append(kind: BoundaryKind, absolute_hour: int) -> None:
        candidates.append(
            _make_boundary(
                segment.segment_id,
                kind,
                absolute_hour,
                calendar_version=segment.start.calendar_version,
                epoch_id=segment.start.epoch_id,
                world_timezone=segment.start.world_timezone,
            ),
        )
        if len(candidates) > max_boundaries:
            raise ClockPlanningError(
                "activity_contract_required",
                "行动跨越的时间边界过多，必须由有界 activity/checkpoint contract 处理",
            )

    for day_index in range(first_day_index, last_day_index + 1):
        absolute_hour = day_index * 24
        projection = projection_from_absolute_hour(
            absolute_hour,
            calendar_version=segment.start.calendar_version,
        )
        append("day", absolute_hour)
        if projection.day == 1:
            append("month", absolute_hour)
            if projection.month == 1 and not projection.is_leap_month:
                append("year", absolute_hour)
        if not projection.is_leap_month and projection.day in {6, 21}:
            append("solar_term", absolute_hour)

    append("end", end_hour)

    deduplicated = {
        (boundary.absolute_hour, boundary.kind, boundary.boundary_key): boundary
        for boundary in candidates
    }
    boundaries = tuple(
        sorted(
            deduplicated.values(),
            key=lambda boundary: (
                boundary.absolute_hour,
                _BOUNDARY_ORDER[boundary.kind],
                boundary.boundary_key,
            ),
        ),
    )
    if len(boundaries) > max_boundaries:
        raise ClockPlanningError(
            "activity_contract_required",
            "行动跨越的时间边界过多，必须由有界 activity/checkpoint contract 处理",
        )
    return boundaries


class ClockConsumerRegistry:
    def __init__(self, consumers: Iterable[ClockConsumer] = ()) -> None:
        self._consumers: dict[str, ClockConsumer] = {}
        for consumer in consumers:
            self.register(consumer)

    def register(self, consumer: ClockConsumer) -> None:
        name = getattr(consumer, "name", "")
        version = getattr(consumer, "version", "")
        order = getattr(consumer, "order", None)
        boundary_kinds = frozenset(getattr(consumer, "boundary_kinds", ()))
        if not isinstance(name, str) or not name.strip():
            raise ClockPlanningError(
                "invalid_clock_consumer",
                "clock consumer name must be nonblank",
            )
        if not isinstance(version, str) or not version.strip():
            raise ClockPlanningError(
                "invalid_clock_consumer",
                "clock consumer version must be nonblank",
            )
        if isinstance(order, bool) or not isinstance(order, int):
            raise ClockPlanningError(
                "invalid_clock_consumer",
                "clock consumer order must be an integer",
            )
        if not boundary_kinds or not boundary_kinds.issubset(_BOUNDARY_ORDER):
            raise ClockPlanningError(
                "invalid_clock_consumer",
                "clock consumer boundary_kinds are invalid",
            )
        if name in self._consumers:
            raise ClockPlanningError(
                "duplicate_clock_consumer",
                f"clock consumer already registered: {name}",
            )
        self._consumers[name] = consumer

    @property
    def consumers(self) -> tuple[ClockConsumer, ...]:
        return tuple(
            sorted(
                self._consumers.values(),
                key=lambda consumer: (consumer.order, consumer.name, consumer.version),
            ),
        )

    def build_invocations(
        self,
        segment: ElapsedSegment,
        boundaries: Sequence[TimeBoundary],
    ) -> tuple[ClockConsumerInvocation, ...]:
        invocations: list[ClockConsumerInvocation] = []
        for boundary in boundaries:
            for consumer in self.consumers:
                if boundary.kind not in consumer.boundary_kinds:
                    continue
                ordinal = len(invocations)
                invocations.append(
                    ClockConsumerInvocation(
                        invocation_id=_stable_id(
                            segment.segment_id,
                            boundary.boundary_id,
                            consumer.name,
                            consumer.version,
                        ),
                        consumer_name=consumer.name,
                        consumer_version=consumer.version,
                        consumer_order=consumer.order,
                        segment_id=segment.segment_id,
                        boundary_id=boundary.boundary_id,
                        boundary_kind=boundary.kind,
                        ordinal=ordinal,
                    ),
                )
        return tuple(invocations)

    def dispatch(
        self,
        state: GameState,
        plan: ElapsedSegmentPlan,
    ) -> tuple[WorldDelta, ...]:
        """Run each persisted invocation once and return typed delta proposals."""

        boundaries = {
            boundary.boundary_id: boundary for boundary in plan.boundaries
        }
        produced: list[WorldDelta] = []
        delta_ids: set[str] = set()
        for invocation in plan.consumer_invocations:
            consumer = self._consumers.get(invocation.consumer_name)
            if (
                consumer is None
                or consumer.version != invocation.consumer_version
                or consumer.order != invocation.consumer_order
                or invocation.boundary_kind not in consumer.boundary_kinds
            ):
                raise ClockPlanningError(
                    "clock_consumer_registry_mismatch",
                    "persisted clock invocation does not match the active registry",
                )
            boundary = boundaries[invocation.boundary_id]
            try:
                deltas = _WORLD_DELTA_LIST_ADAPTER.validate_python(
                    list(
                        consumer.consume(
                            state=state.model_copy(deep=True),
                            segment=plan.segment,
                            boundary=boundary,
                            invocation=invocation,
                        ),
                    ),
                )
            except (ValidationError, TypeError, ValueError) as exc:
                raise ClockPlanningError(
                    "invalid_clock_consumer_result",
                    f"clock consumer returned invalid deltas: {consumer.name}",
                ) from exc
            for delta in deltas:
                delta_id = str(delta.delta_id)
                if delta_id in delta_ids:
                    raise ClockPlanningError(
                        "duplicate_clock_consumer_delta",
                        "clock consumers returned a duplicate delta identity",
                    )
                delta_ids.add(delta_id)
                produced.append(delta)
        return tuple(produced)


def plan_elapsed_segment(
    *,
    source_action_id: ClientActionId,
    start: WorldInstant,
    duration: Duration,
    registry: ClockConsumerRegistry | None = None,
    max_boundaries: int = MAX_BOUNDARIES_PER_SEGMENT,
) -> ElapsedSegmentPlan:
    try:
        normalized = normalize_duration(start, duration)
        segment = ElapsedSegment(
            segment_id=_stable_id(
                source_action_id,
                start.calendar_version,
                start.epoch_id,
                start.world_timezone,
                start.absolute_hour,
                normalized.end.absolute_hour,
            ),
            source_action_id=source_action_id,
            start=normalized.start,
            end=normalized.end,
            elapsed_hours=normalized.elapsed_hours,
        )
        boundaries = enumerate_boundaries(
            segment,
            max_boundaries=max_boundaries,
        )
    except CalendarError as exc:
        raise ClockPlanningError(
            "invalid_time_contract",
            "duration cannot be normalized against the world's calendar",
        ) from exc

    active_registry = registry or ClockConsumerRegistry()
    invocations = active_registry.build_invocations(segment, boundaries)
    return ElapsedSegmentPlan(
        normalized_duration=normalized,
        segment=segment,
        boundaries=boundaries,
        consumer_invocations=invocations,
    )
