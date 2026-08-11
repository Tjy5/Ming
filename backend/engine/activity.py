"""Pure durable-activity and checkpoint state transitions.

The immutable world snapshot stores the activity graph. SQLite settlement/action
identity remains the commit authority; this module only plans and validates the
next state that will be committed atomically with one checkpoint settlement.
"""

from __future__ import annotations

import hashlib
from uuid import NAMESPACE_URL, UUID, uuid5

from models.game import GameState
from models.settlement import (
    ActionIntent,
    AdjudicationProposal,
)
from models.world import (
    Activity,
    ActivityCheckpoint,
    ActivityId,
    CheckpointId,
    ClientActionId,
    DeltaId,
    ElapsedSegmentPlan,
    SettlementId,
    VersionId,
    WorldInstant,
)

from .calendar import ensure_game_time_clock, normalize_duration, projection_from_absolute_hour
from .clock import ClockConsumerRegistry, plan_elapsed_segment


class ActivityContractError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def require_available_executor(state: GameState, activity: Activity) -> None:
    """Fail closed when a persisted actual executor can no longer act."""
    executor_id = activity.actual_executor_id
    if executor_id is None:
        return
    entity = state.entity_registry.get(executor_id)
    if entity is None or entity.status != "active" or not entity.available:
        raise ActivityContractError(
            "activity_executor_unavailable",
            "活动实际执行者不存在、已失效或当前不可行动；请改派或终止活动",
        )


def rebase_pending_checkpoints(
    state: GameState,
    result_version_id: VersionId,
) -> GameState:
    """Bind live checkpoints to a new version and reconcile elapsed world time.

    Ordinary actions may advance the clock while another activity is in flight.
    An in-progress activity accrues that elapsed time until its next checkpoint;
    paused/decision-bound activities instead keep their remaining duration and
    shift their schedule forward. Crossing an unprocessed checkpoint fails
    closed so an external action cannot silently skip its re-adjudication.
    """
    changed = state.model_copy(deep=True)
    current = ensure_game_time_clock(changed.time.model_copy(deep=True))
    for index, activity in enumerate(changed.activities):
        if activity.status not in {"in_progress", "awaiting_player_decision", "paused"}:
            continue
        rebased = activity.model_copy(deep=True)
        pending = [item for item in rebased.checkpoints if item.status == "pending"]
        if len(pending) != 1:
            raise ActivityContractError(
                "invalid_activity_checkpoint_state",
                "活动必须恰有一个待处理检查点",
            )
        checkpoint = pending[0]
        if current.absolute_hour < checkpoint.planned_start.absolute_hour:
            raise ActivityContractError(
                "activity_clock_regression",
                "世界时钟早于活动检查点起点",
            )

        if rebased.status == "in_progress":
            if current.absolute_hour >= checkpoint.planned_end.absolute_hour:
                raise ActivityContractError(
                    "activity_checkpoint_due",
                    "外部行动不得越过尚未处理的活动检查点",
                )
            elapsed = current.absolute_hour - checkpoint.planned_start.absolute_hour
            rebased.elapsed_hours += elapsed
            rebased.remaining_hours = max(
                0,
                rebased.planned_end.absolute_hour - current.absolute_hour,
            )
            next_start = current
            next_end = checkpoint.planned_end
        else:
            next_start = current
            next_end = _instant_like(
                current,
                current.absolute_hour
                + min(rebased.remaining_hours, rebased.checkpoint_horizon_hours),
            )
            rebased.planned_end = _instant_like(
                current,
                current.absolute_hour + rebased.remaining_hours,
            )
            rebased.planned_elapsed_hours = (
                rebased.planned_end.absolute_hour - rebased.started_at.absolute_hour
            )

        rebased.checkpoints = [
            item.model_copy(
                update={
                    "expected_parent_version_id": result_version_id,
                    "planned_start": next_start,
                    "planned_end": next_end,
                },
            )
            if item.checkpoint_id == checkpoint.checkpoint_id
            else item
            for item in rebased.checkpoints
        ]
        changed.activities[index] = Activity.model_validate(rebased.model_dump())
    return GameState.model_validate(changed.model_dump())


def _checkpoint_roll(
    checkpoint: ActivityCheckpoint,
    projected: GameState,
    proposal: AdjudicationProposal,
) -> tuple[str | None, int | None]:
    """Derive one retry-stable public roll only for explicitly risky segments."""
    if proposal.uncertainty is None or proposal.uncertainty < 0.5:
        return None, None
    payload = (
        f"checkpoint-roll-v1:{checkpoint.checkpoint_id}:"
        f"{checkpoint.planned_start.absolute_hour}:{checkpoint.planned_end.absolute_hour}:"
        f"{projected.execution_rng_seed or 0}"
    ).encode("utf-8")
    roll_key = hashlib.sha256(payload).hexdigest()
    return roll_key, int(roll_key[:16], 16) % 100 + 1


def _stable_uuid(kind: str, *parts: object) -> UUID:
    payload = ":".join((kind, *(str(part) for part in parts)))
    return uuid5(NAMESPACE_URL, payload)


def _instant_like(reference: WorldInstant, absolute_hour: int) -> WorldInstant:
    return WorldInstant(
        absolute_hour=absolute_hour,
        calendar_version=reference.calendar_version,
        epoch_id=reference.epoch_id,
        world_timezone=reference.world_timezone,
    )


def _checkpoint_end(
    start: WorldInstant,
    activity_end: WorldInstant,
    horizon_hours: int,
) -> WorldInstant:
    latest = min(activity_end.absolute_hour, start.absolute_hour + horizon_hours)
    first_day = start.absolute_hour // 24 + 1
    last_day = latest // 24
    for day_index in range(first_day, last_day + 1):
        absolute_hour = day_index * 24
        projection = projection_from_absolute_hour(
            absolute_hour,
            calendar_version=start.calendar_version,
        )
        if projection.day == 1:
            latest = absolute_hour
            break
    return _instant_like(start, latest)


def _new_checkpoint(
    *,
    activity_id: ActivityId,
    sequence: int,
    expected_parent_version_id: VersionId,
    start: WorldInstant,
    activity_end: WorldInstant,
    horizon_hours: int,
) -> ActivityCheckpoint:
    checkpoint_id = CheckpointId(
        _stable_uuid("activity-checkpoint", activity_id, sequence),
    )
    client_action_id = ClientActionId(
        _stable_uuid("activity-checkpoint-action", checkpoint_id),
    )
    return ActivityCheckpoint(
        checkpoint_id=checkpoint_id,
        activity_id=activity_id,
        sequence=sequence,
        client_action_id=client_action_id,
        expected_parent_version_id=expected_parent_version_id,
        planned_start=start,
        planned_end=_checkpoint_end(start, activity_end, horizon_hours),
    )


def create_activity(
    *,
    state: GameState,
    intent: ActionIntent,
    proposal: AdjudicationProposal,
    start: WorldInstant,
    result_version_id: VersionId,
) -> Activity:
    candidate = proposal.activity_candidate
    duration = proposal.duration_candidate
    if candidate is None or duration is None:
        raise ActivityContractError(
            "invalid_activity_candidate",
            "activity creation requires candidate metadata and planned duration",
        )
    normalized = normalize_duration(start, duration)
    activity_id = ActivityId(
        _stable_uuid("activity", intent.game_id, intent.branch_id, intent.client_action_id),
    )
    first_checkpoint = _new_checkpoint(
        activity_id=activity_id,
        sequence=1,
        expected_parent_version_id=result_version_id,
        start=start,
        activity_end=normalized.end,
        horizon_hours=candidate.checkpoint_horizon_hours,
    )
    activity = Activity(
        activity_id=activity_id,
        kind=candidate.kind,
        intent=intent.raw_text,
        target_summary=candidate.target_summary,
        requested_executor_id=intent.requested_executor_id,
        actual_executor_id=proposal.actual_executor_id,
        started_at=start,
        planned_duration=duration,
        planned_end=normalized.end,
        planned_elapsed_hours=normalized.elapsed_hours,
        remaining_hours=normalized.elapsed_hours,
        checkpoint_horizon_hours=candidate.checkpoint_horizon_hours,
        next_checkpoint_id=first_checkpoint.checkpoint_id,
        prerequisites=list(candidate.prerequisites),
        planned_effects=list(candidate.planned_effects),
        checkpoints=[first_checkpoint],
        created_by_action_id=intent.client_action_id,
    )
    require_available_executor(state, activity)
    return activity


def find_activity(state: GameState, activity_id: ActivityId) -> tuple[int, Activity]:
    matches = [
        (index, activity)
        for index, activity in enumerate(state.activities)
        if activity.activity_id == activity_id
    ]
    if len(matches) != 1:
        raise ActivityContractError(
            "activity_not_found",
            "活动不存在或活动身份不唯一",
        )
    return matches[0]


def require_pending_checkpoint(
    state: GameState,
    intent: ActionIntent,
) -> tuple[int, Activity, ActivityCheckpoint]:
    if (
        intent.activity_id is None
        or intent.checkpoint_id is None
        or intent.checkpoint_sequence is None
    ):
        raise ActivityContractError(
            "invalid_activity_command",
            "活动命令缺少 activity/checkpoint identity",
        )
    index, activity = find_activity(state, intent.activity_id)
    pending = [
        checkpoint
        for checkpoint in activity.checkpoints
        if checkpoint.status == "pending"
    ]
    if (
        len(pending) != 1
        or pending[0].checkpoint_id != intent.checkpoint_id
        or pending[0].sequence != intent.checkpoint_sequence
        or activity.next_checkpoint_id != intent.checkpoint_id
    ):
        raise ActivityContractError(
            "stale_activity_checkpoint",
            "活动命令引用的检查点已不是当前待处理检查点",
        )
    checkpoint = pending[0]
    if checkpoint.expected_parent_version_id != intent.expected_parent_version_id:
        raise ActivityContractError(
            "stale_activity_checkpoint",
            "活动检查点的预期父版本与请求不一致",
        )
    return index, activity, checkpoint


def plan_checkpoint(
    checkpoint: ActivityCheckpoint,
    *,
    registry: ClockConsumerRegistry | None = None,
) -> ElapsedSegmentPlan:
    duration_hours = (
        checkpoint.planned_end.absolute_hour - checkpoint.planned_start.absolute_hour
    )
    from models.world import Duration

    return plan_elapsed_segment(
        source_action_id=checkpoint.client_action_id,
        start=checkpoint.planned_start,
        duration=Duration(unit="hour", value=duration_hours),
        registry=registry,
    )


def apply_activity_command(
    state: GameState,
    intent: ActionIntent,
    *,
    result_version_id: VersionId,
) -> tuple[GameState, Activity]:
    index, activity, checkpoint = require_pending_checkpoint(state, intent)
    command = intent.activity_command
    changed = state.model_copy(deep=True)
    activity = activity.model_copy(deep=True)

    if command == "pause":
        if activity.status not in {"in_progress", "awaiting_player_decision"}:
            raise ActivityContractError("invalid_activity_transition", "当前活动不能暂停")
        activity.status = "paused"
        activity.pending_decision = None
    elif command == "cancel":
        if activity.status in {"cancelled", "failed", "completed"}:
            raise ActivityContractError("no_state_change", "活动已经结束")
        activity.status = "cancelled"
        activity.pending_decision = None
        activity.next_checkpoint_id = None
        activity.checkpoints = [
            item
            for item in activity.checkpoints
            if item.checkpoint_id != checkpoint.checkpoint_id
        ]
    elif command == "resume":
        if activity.status not in {"paused", "awaiting_player_decision"}:
            raise ActivityContractError("invalid_activity_transition", "当前活动不能恢复")
        activity.status = "in_progress"
        activity.pending_decision = None
    elif command == "redirect":
        if not intent.redirect_text:
            raise ActivityContractError("invalid_activity_command", "改道命令缺少新意图")
        activity.intent = intent.redirect_text
        activity.target_summary = intent.redirect_text
        activity.status = "in_progress"
        activity.pending_decision = None
    elif command == "reassign":
        if intent.replacement_executor_id is None:
            raise ActivityContractError("invalid_activity_command", "改派命令缺少执行者")
        entity = changed.entity_registry.get(intent.replacement_executor_id)
        if entity is None or entity.status != "active" or not entity.available:
            raise ActivityContractError(
                "activity_executor_unavailable",
                "改派执行者当前不可用",
            )
        activity.actual_executor_id = intent.replacement_executor_id
        activity.status = "in_progress"
        activity.pending_decision = None
    else:
        raise ActivityContractError(
            "invalid_activity_command",
            "该活动命令必须走检查点复裁路径",
        )

    if activity.next_checkpoint_id is not None:
        activity.checkpoints = [
            item.model_copy(update={"expected_parent_version_id": result_version_id})
            if item.checkpoint_id == activity.next_checkpoint_id
            else item
            for item in activity.checkpoints
        ]
    changed.activities[index] = Activity.model_validate(activity.model_dump())
    return changed, changed.activities[index]


def finish_checkpoint(
    projected: GameState,
    *,
    intent: ActionIntent,
    plan: ElapsedSegmentPlan,
    proposal: AdjudicationProposal,
    settlement_id: SettlementId,
    result_version_id: VersionId,
    committed_delta_ids: list[DeltaId],
) -> tuple[GameState, Activity]:
    index, activity, checkpoint = require_pending_checkpoint(projected, intent)
    decision = proposal.activity_decision
    if decision is None:
        raise ActivityContractError(
            "activity_decision_required",
            "活动检查点缺少复裁决定",
        )

    activity = activity.model_copy(deep=True)
    roll_key, roll_value = _checkpoint_roll(checkpoint, projected, proposal)
    completed_checkpoint = checkpoint.model_copy(
        update={
            "status": "completed",
            "settlement_id": settlement_id,
            "version_id": result_version_id,
            "crossed_boundary_ids": [item.boundary_id for item in plan.boundaries],
            "committed_delta_ids": committed_delta_ids,
            "interruption_facts": list(decision.interruption_facts),
            "roll_key": roll_key,
            "roll_value": roll_value,
        },
    )
    activity.checkpoints = [
        completed_checkpoint if item.checkpoint_id == checkpoint.checkpoint_id else item
        for item in activity.checkpoints
    ]
    activity.elapsed_hours += plan.segment.elapsed_hours
    activity.remaining_hours = max(
        0,
        activity.planned_end.absolute_hour - plan.segment.end.absolute_hour,
    )
    activity.committed_segment_effects.extend(proposal.immediate_changes)
    activity.interruption_facts.extend(decision.interruption_facts)
    activity.pending_decision = None

    if decision.remaining_duration is not None:
        revised = normalize_duration(plan.segment.end, decision.remaining_duration)
        activity.planned_end = revised.end
        activity.planned_elapsed_hours = activity.elapsed_hours + revised.elapsed_hours
        activity.remaining_hours = revised.elapsed_hours

    transition = decision.transition
    if transition == "await_player":
        activity.status = "awaiting_player_decision"
        activity.pending_decision = decision.pending_decision
    elif transition == "pause":
        activity.status = "paused"
    elif transition == "fail":
        activity.status = "failed"
        activity.remaining_hours = 0
    elif transition == "complete" or activity.remaining_hours == 0:
        activity.status = "completed"
        activity.remaining_hours = 0
    else:
        activity.status = "in_progress"
        if transition == "redirect":
            activity.target_summary = decision.reason

    if activity.status in {"cancelled", "failed", "completed"}:
        activity.next_checkpoint_id = None
    else:
        next_sequence = checkpoint.sequence + 1
        next_checkpoint = _new_checkpoint(
            activity_id=activity.activity_id,
            sequence=next_sequence,
            expected_parent_version_id=result_version_id,
            start=plan.segment.end,
            activity_end=activity.planned_end,
            horizon_hours=activity.checkpoint_horizon_hours,
        )
        activity.checkpoints.append(next_checkpoint)
        activity.next_checkpoint_id = next_checkpoint.checkpoint_id
        activity.checkpoint_sequence = next_sequence

    changed = projected.model_copy(deep=True)
    changed.activities[index] = Activity.model_validate(activity.model_dump())
    return changed, changed.activities[index]


def consumer_names(plan: ElapsedSegmentPlan) -> list[str]:
    return [
        f"{invocation.consumer_name}@{invocation.consumer_version}"
        for invocation in plan.consumer_invocations
    ]
