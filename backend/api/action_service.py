from __future__ import annotations

import asyncio
import json
import re
import threading
import weakref
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException
from pydantic import ValidationError

from db import worlds
from engine.activity import (
    ActivityContractError,
    apply_activity_command,
    create_activity,
    finish_checkpoint,
    find_activity,
    plan_checkpoint,
    rebase_pending_checkpoints,
    require_available_executor,
    require_pending_checkpoint,
)
from engine.calendar import advance_game_time, ensure_game_time_clock
from engine.clock import ClockConsumerRegistry, ClockPlanningError, plan_elapsed_segment
from engine.elapsed_consumers import default_clock_registry
from engine.execution import build_executor_facts
from engine.rng import roll_for_action
from engine.settlement import (
    SettlementValidationError,
    apply_terminal_world_deltas_with_facts,
    apply_world_deltas,
    apply_world_deltas_with_facts,
    validate_adjudication_proposal,
    validate_final_state,
)
from engine.lifecycle import LifecyclePlanner
from models.game import GameState
from models.settlement import (
    ActionIntent,
    AdjudicationProposal,
    ProviderAttribution,
    PlayerWorldDelta,
    SettlementCommitResult,
    WorldDelta,
)
from models.world import (
    Activity,
    ActivityId,
    BranchId,
    ElapsedSegmentPlan,
    GameId,
    SettlementId,
    VersionId,
    new_settlement_id,
    new_version_id,
)
from models.world_state import AppliedMetricAttribution, ExecutorFacts, RollRecord
from ai.prompts import ADJUDICATION_SYSTEM_PROMPT


class ActionAdjudicator(Protocol):
    async def adjudicate(
        self,
        intent: ActionIntent,
        state: GameState,
    ) -> AdjudicationProposal: ...


class ActionTimePlanner(Protocol):
    def plan_segment(
        self,
        intent: ActionIntent,
        state: GameState,
        proposal: AdjudicationProposal,
    ) -> ElapsedSegmentPlan | None: ...


class ActionWorldStateApplier(Protocol):
    def apply_world_deltas(
        self,
        state: GameState,
        deltas: list[WorldDelta],
        time_plan: ElapsedSegmentPlan | None,
    ) -> GameState: ...


@dataclass(frozen=True)
class ActionExecution:
    state: GameState
    result: SettlementCommitResult


@dataclass(frozen=True)
class ActivityBatchExecution:
    state: GameState
    activity: Activity
    results: tuple[SettlementCommitResult, ...]
    processing: bool
    continuation_cursor: str | None


class ActionAdjudicationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class NoopTimePlanner:
    def plan_segment(
        self,
        intent: ActionIntent,
        state: GameState,
        proposal: AdjudicationProposal,
    ) -> None:
        del intent, state
        if proposal.duration_candidate or proposal.activity_candidate:
            raise SettlementValidationError(
                "time_contract_unavailable",
                "裁决提出了耗时/活动，但动态时间契约尚未接入",
            )
        return None


class DefaultTimePlanner:
    def __init__(self, registry: ClockConsumerRegistry | None = None) -> None:
        self.registry = registry or ClockConsumerRegistry()

    def plan_segment(
        self,
        intent: ActionIntent,
        state: GameState,
        proposal: AdjudicationProposal,
    ) -> ElapsedSegmentPlan | None:
        if proposal.activity_candidate is not None:
            return None
        if proposal.duration_candidate is None:
            return None

        game_time = state.time.model_copy(deep=True)
        start = ensure_game_time_clock(game_time)
        try:
            return plan_elapsed_segment(
                source_action_id=intent.client_action_id,
                start=start,
                duration=proposal.duration_candidate,
                registry=self.registry,
            )
        except ClockPlanningError as exc:
            raise SettlementValidationError(exc.code, exc.message) from exc


class DefaultWorldStateApplier:
    def __init__(self, registry: ClockConsumerRegistry | None = None) -> None:
        self.registry = registry or ClockConsumerRegistry()

    def apply_world_deltas(
        self,
        state: GameState,
        deltas: list[WorldDelta],
        time_plan: ElapsedSegmentPlan | None,
    ) -> GameState:
        changed, _, _ = self.apply_with_facts(state, deltas, time_plan)
        return changed

    def apply_with_facts(
        self,
        state: GameState,
        deltas: list[WorldDelta],
        time_plan: ElapsedSegmentPlan | None,
        *,
        executor_facts: ExecutorFacts | None = None,
        roll: RollRecord | None = None,
        terminal_settlement_id: SettlementId | None = None,
        terminal_version_id: VersionId | None = None,
    ) -> tuple[GameState, list[WorldDelta], list[AppliedMetricAttribution]]:
        if (terminal_settlement_id is None) != (terminal_version_id is None):
            raise SettlementValidationError(
                "invalid_terminal_identity",
                "terminal settlement/version ids 必须成对提供",
            )
        if terminal_settlement_id is not None and terminal_version_id is not None:
            changed, attribution = apply_terminal_world_deltas_with_facts(
                state,
                deltas,
                settlement_id=terminal_settlement_id,
                version_id=terminal_version_id,
                executor_facts=executor_facts,
                roll=roll,
            )
        else:
            changed, attribution = apply_world_deltas_with_facts(
                state,
                deltas,
                executor_facts=executor_facts,
                roll=roll,
            )
        if time_plan is None:
            return changed, [], attribution

        try:
            consumer_deltas = list(self.registry.dispatch(changed, time_plan))
        except ClockPlanningError as exc:
            raise SettlementValidationError(exc.code, exc.message) from exc
        if consumer_deltas:
            changed = apply_world_deltas(changed, consumer_deltas)

        current = ensure_game_time_clock(changed.time)
        if current != time_plan.segment.start:
            raise SettlementValidationError(
                "time_plan_stale",
                "time plan 的起点与当前世界时钟不一致",
            )
        applied = advance_game_time(
            changed.time,
            time_plan.normalized_duration.duration,
        )
        if applied != time_plan.normalized_duration:
            raise SettlementValidationError(
                "time_plan_mismatch",
                "time plan 与最终世界时钟推进结果不一致",
            )
        try:
            return GameState.model_validate(changed.model_dump()), consumer_deltas, attribution
        except ValidationError as exc:
            raise SettlementValidationError(
                "invalid_final_state",
                "time plan 应用后的世界状态未通过模型校验",
            ) from exc


class AIActionAdjudicator:
    """Strict JSON adjudication using exactly one provider call.

    Provider/schema failures remain pre-commit errors. This adapter never calls
    a rule parser, retry loop, narrative template, or fallback adjudicator.
    """

    def __init__(self, provider_loader):
        self._provider_loader = provider_loader

    @staticmethod
    def _decode_proposal(text: str) -> dict:
        """Decode one provider JSON object without repairing its contract.

        Some OpenAI-compatible gateways still wrap JSON in a fenced block or
        prepend a short reasoning marker even when ``response_format`` is set.
        We tolerate only that transport noise, then hand the untouched object to
        Pydantic.  No defaults, aliases, delta fabrication, or rule fallback are
        applied here: malformed proposal data remains a pre-commit failure.
        """

        if not isinstance(text, str) or not text.strip():
            raise ValueError("empty adjudication response")
        payload = text.strip()
        # DeepSeek may emit a reasoning block before the requested JSON. Only
        # this explicit provider wrapper is tolerated; arbitrary leading prose
        # remains a contract violation.
        think_match = re.match(r"^<think>[\s\S]*?</think>\s*", payload)
        if think_match:
            payload = payload[think_match.end():].strip()

        # Fenced JSON is also a known transport wrapper. The opening language
        # tag must be `json` (or omitted), and the closing marker must be exactly
        # three backticks; ` ```json` is never a valid closing marker.
        if payload.startswith("```"):
            opening = "```json" if payload.startswith("```json") else "```"
            payload = payload[len(opening):].lstrip()
            if not payload.endswith("```"):
                raise ValueError("adjudication response has an unclosed JSON fence")
            payload = payload[:-3].rstrip()

        if not payload.startswith("{"):
            raise ValueError("adjudication response does not contain a JSON object")
        decoder = json.JSONDecoder()
        try:
            value, end = decoder.raw_decode(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("adjudication response is not valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("adjudication response must be a JSON object")
        trailing = payload[end:].strip()
        if trailing:
            raise ValueError("adjudication response contains trailing text")
        return value

    async def adjudicate(
        self,
        intent: ActionIntent,
        state: GameState,
    ) -> AdjudicationProposal:
        try:
            provider = self._provider_loader()
        except HTTPException:
            # _get_provider already exposes the safe, typed configuration 409.
            raise
        except Exception as exc:
            raise ActionAdjudicationError(
                "adjudication_provider_error",
                "AI 裁决调用失败，世界状态未提交",
            ) from exc
        if intent.activity_command == "continue":
            activity_instruction = (
                "For activity checkpoint continuation, do not return duration_candidate or a nested "
                "activity_candidate; return activity_decision with transition, reason, interruption facts, "
                "and pending_decision only when player choice is required. "
            )
        elif intent.activity_command is None:
            activity_instruction = (
                "This submitted world-changing action must return duration_candidate and duration_reason. "
                "For a long action, pair duration_candidate with typed activity_candidate metadata. "
            )
        else:
            activity_instruction = (
                "For an activity lifecycle command, do not return a new duration or activity candidate. "
            )
        public_roll = roll_for_action(intent, state)
        adjudication_intent = intent.model_dump_json(
            exclude={"suggestion_id", "visible_context_version"},
        )
        prompt = (
            f"{activity_instruction}"
            "Judge the player's action only from the supplied current-world snapshot. "
            "Do not use historical canon as a whitelist.\n"
            f"ACTION_INTENT={adjudication_intent}\n"
            f"PUBLIC_ROLL={public_roll.model_dump_json() if public_roll else 'none'}\n"
            f"CURRENT_WORLD={state.model_dump_json()}"
        )
        try:
            generated = await provider.generate_text_once(
                prompt,
                system_prompt=ADJUDICATION_SYSTEM_PROMPT,
                max_output_tokens=4096,
                response_json=True,
            )
        except Exception as exc:
            raise ActionAdjudicationError(
                "adjudication_provider_error",
                "AI 裁决调用失败，世界状态未提交",
            ) from exc

        try:
            raw = self._decode_proposal(generated.text)
            provider_payload = raw.get("provider", {})
            if not isinstance(provider_payload, dict) or provider_payload:
                raise ValueError("provider attribution must be an empty object")
            proposal = AdjudicationProposal.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            raise ActionAdjudicationError(
                "adjudication_invalid_response",
                "AI 裁决响应不符合结构契约，世界状态未提交",
            ) from exc

        proposal.provider = ProviderAttribution(
            request_id=generated.provider_request_id,
        )
        return proposal

    def adjudicate_sync(
        self,
        intent: ActionIntent,
        state: GameState,
    ) -> AdjudicationProposal:
        return asyncio.run(self.adjudicate(intent, state))


class ActionService:
    def __init__(
        self,
        *,
        adjudicator: ActionAdjudicator,
        time_planner: ActionTimePlanner | None = None,
        world_state_applier: ActionWorldStateApplier | None = None,
        clock_registry: ClockConsumerRegistry | None = None,
        lifecycle_planner: LifecyclePlanner | None = None,
    ) -> None:
        self._adjudicator = adjudicator
        self._clock_registry = clock_registry or default_clock_registry()
        self._time_planner = time_planner or DefaultTimePlanner(self._clock_registry)
        self._world_state_applier = world_state_applier or DefaultWorldStateApplier(
            self._clock_registry,
        )
        self._lifecycle_planner = lifecycle_planner
        self._action_locks: weakref.WeakValueDictionary[
            tuple[str, str, str], asyncio.Lock
        ] = weakref.WeakValueDictionary()
        self._action_locks_guard = threading.Lock()

    def _lock_for(self, intent: ActionIntent) -> asyncio.Lock:
        key = (
            str(intent.game_id),
            str(intent.branch_id),
            str(intent.client_action_id),
        )
        with self._action_locks_guard:
            lock = self._action_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._action_locks[key] = lock
            return lock

    async def execute(self, intent: ActionIntent) -> ActionExecution:
        # Suppress duplicate provider calls in the current server process. The
        # repository unique key and branch-head CAS remain the cross-process
        # authority and are rechecked below.
        async with self._lock_for(intent):
            return await self._execute_once(intent)

    async def _execute_once(self, intent: ActionIntent) -> ActionExecution:
        replayed = worlds.replay_action_request(intent)
        if replayed is not None:
            snapshot = worlds.load_version(replayed.version.version_id)
            return ActionExecution(state=snapshot.state, result=replayed)

        snapshot = worlds.load_branch_head(intent.game_id, intent.branch_id)
        if snapshot.ref.version_id != intent.expected_parent_version_id:
            raise worlds.StaleParentVersionError(
                intent.expected_parent_version_id,
                snapshot.ref.version_id,
            )
        previous = snapshot.state.model_copy(deep=True)
        if previous.player_world_status.life_status == "dead":
            raise worlds.WorldTerminalStateError()

        if intent.activity_command is not None:
            if intent.activity_command == "continue":
                return await self._continue_activity(intent, previous)
            return self._execute_activity_command(intent, previous)

        proposal = await self._adjudicator.adjudicate(intent, previous.model_copy(deep=True))
        terminal_death = any(
            isinstance(delta, PlayerWorldDelta) and delta.operation == "death"
            for delta in proposal.deltas
        )
        validate_adjudication_proposal(
            intent,
            previous,
            proposal,
            allow_terminal_death=terminal_death,
        )
        if proposal.activity_candidate is not None:
            return self._create_activity(intent, previous, proposal)
        time_plan = self._time_planner.plan_segment(intent, previous, proposal)
        roll = roll_for_action(intent, previous)
        settlement_id = new_settlement_id()
        version_id = new_version_id()
        try:
            executor_facts = build_executor_facts(
                previous,
                requested_executor_id=proposal.requested_executor_id,
                actual_executor_id=proposal.actual_executor_id,
                execution_status=proposal.execution_status,
                action_kind=intent.action_kind,
            )
        except ValueError as exc:
            raise SettlementValidationError("invalid_executor", str(exc)) from exc
        world_state_attribution: list[AppliedMetricAttribution] = []
        proposal_for_commit = proposal
        if isinstance(self._world_state_applier, DefaultWorldStateApplier):
            changed, consumer_deltas, world_state_attribution = self._world_state_applier.apply_with_facts(
                previous,
                proposal.deltas,
                time_plan,
                executor_facts=executor_facts,
                roll=roll,
                terminal_settlement_id=settlement_id if terminal_death else None,
                terminal_version_id=version_id if terminal_death else None,
            )
            if consumer_deltas:
                proposal_for_commit = proposal.model_copy(
                    update={"deltas": [*proposal.deltas, *consumer_deltas]},
                )
        else:
            if terminal_death:
                raise SettlementValidationError(
                    "terminal_contract_unavailable",
                    "自定义 world-state applier 未声明 terminal death contract",
                )
            changed = self._world_state_applier.apply_world_deltas(
                previous,
                proposal.deltas,
                time_plan,
            )
        if self._lifecycle_planner is not None:
            lifecycle = self._lifecycle_planner.propose(
                previous=previous.model_copy(deep=True),
                changed=changed.model_copy(deep=True),
            )
            if lifecycle.deltas:
                changed = apply_world_deltas(changed, list(lifecycle.deltas))
                proposal_for_commit = proposal_for_commit.model_copy(
                    update={
                        "deltas": [*proposal_for_commit.deltas, *lifecycle.deltas],
                    },
                )
        validate_final_state(previous, changed)

        # The provider call happens outside SQLite. Recheck before entering the
        # transaction; commit_settlement performs the final CAS under BEGIN IMMEDIATE.
        current = worlds.get_branch_head(intent.game_id, intent.branch_id)
        if current.version_id != intent.expected_parent_version_id:
            raise worlds.StaleParentVersionError(
                intent.expected_parent_version_id,
                current.version_id,
            )

        try:
            changed = rebase_pending_checkpoints(changed, version_id)
        except ActivityContractError as exc:
            raise self._activity_error(exc) from exc
        commit = (
            worlds.commit_terminal_settlement
            if terminal_death
            else worlds.commit_settlement
        )
        result = commit(
            intent,
            changed,
            proposal_for_commit,
            time_plan=time_plan,
            executor_facts=executor_facts,
            world_state_attribution=world_state_attribution,
            rolls=[roll] if roll is not None else [],
            settlement_id=settlement_id,
            version_id=version_id,
        )
        committed = worlds.load_version(result.version.version_id)
        return ActionExecution(state=committed.state, result=result)

    @staticmethod
    def _activity_error(exc: ActivityContractError) -> SettlementValidationError:
        return SettlementValidationError(exc.code, exc.message)

    @staticmethod
    def _assert_head(intent: ActionIntent) -> None:
        current = worlds.get_branch_head(intent.game_id, intent.branch_id)
        if current.version_id != intent.expected_parent_version_id:
            raise worlds.StaleParentVersionError(
                intent.expected_parent_version_id,
                current.version_id,
            )

    def _create_activity(
        self,
        intent: ActionIntent,
        previous: GameState,
        proposal: AdjudicationProposal,
    ) -> ActionExecution:
        settlement_id = new_settlement_id()
        version_id = new_version_id()
        start = ensure_game_time_clock(previous.time)
        try:
            activity = create_activity(
                state=previous,
                intent=intent,
                proposal=proposal,
                start=start,
                result_version_id=version_id,
            )
        except (ActivityContractError, ValueError) as exc:
            if isinstance(exc, ActivityContractError):
                raise self._activity_error(exc) from exc
            raise SettlementValidationError(
                "invalid_activity_candidate",
                "活动计划无法按当前历法规范化",
            ) from exc

        roll = roll_for_action(intent, previous)
        executor_facts = build_executor_facts(
            previous,
            requested_executor_id=proposal.requested_executor_id,
            actual_executor_id=proposal.actual_executor_id,
            execution_status=proposal.execution_status,
            action_kind=intent.action_kind,
        )
        changed, world_state_attribution = apply_world_deltas_with_facts(
            previous,
            proposal.deltas,
            executor_facts=executor_facts,
            roll=roll,
        )
        changed.activities.append(activity)
        changed = GameState.model_validate(changed.model_dump())
        validate_final_state(previous, changed)
        self._assert_head(intent)
        result = worlds.commit_settlement(
            intent,
            changed,
            proposal,
            executor_facts=executor_facts,
            world_state_attribution=world_state_attribution,
            rolls=[roll] if roll is not None else [],
            settlement_id=settlement_id,
            version_id=version_id,
            activity_id=activity.activity_id,
            activity_status=activity.status,
            actual_outcome="activity_created",
        )
        committed = worlds.load_version(result.version.version_id)
        return ActionExecution(state=committed.state, result=result)

    def _execute_activity_command(
        self,
        intent: ActionIntent,
        previous: GameState,
    ) -> ActionExecution:
        settlement_id = new_settlement_id()
        version_id = new_version_id()
        try:
            changed, activity = apply_activity_command(
                previous,
                intent,
                result_version_id=version_id,
            )
        except ActivityContractError as exc:
            raise self._activity_error(exc) from exc
        validate_final_state(previous, changed)
        self._assert_head(intent)
        proposal = AdjudicationProposal(
            result_tier="success",
            key_factors=["玩家明确提交活动状态变更"],
            immediate_changes=[f"activity:{intent.activity_command}"],
            requested_executor_id=activity.requested_executor_id,
            actual_executor_id=activity.actual_executor_id,
            execution_status="completed",
        )
        result = worlds.commit_settlement(
            intent,
            changed,
            proposal,
            settlement_id=settlement_id,
            version_id=version_id,
            activity_id=activity.activity_id,
            checkpoint_id=intent.checkpoint_id,
            checkpoint_sequence=intent.checkpoint_sequence,
            activity_status=activity.status,
            actual_outcome=intent.activity_command,
        )
        committed = worlds.load_version(result.version.version_id)
        return ActionExecution(state=committed.state, result=result)

    async def _continue_activity(
        self,
        intent: ActionIntent,
        previous: GameState,
    ) -> ActionExecution:
        try:
            _, activity, checkpoint = require_pending_checkpoint(previous, intent)
        except ActivityContractError as exc:
            raise self._activity_error(exc) from exc
        if activity.status != "in_progress":
            raise SettlementValidationError(
                "activity_player_decision_required",
                "活动已暂停或等待玩家决定，必须先恢复、改道、改派或终止",
            )
        try:
            require_available_executor(previous, activity)
        except ActivityContractError as exc:
            raise self._activity_error(exc) from exc
        if intent.client_action_id != checkpoint.client_action_id:
            raise SettlementValidationError(
                "checkpoint_identity_mismatch",
                "检查点必须复用其持久化 client_action_id",
            )
        try:
            time_plan = plan_checkpoint(checkpoint, registry=self._clock_registry)
        except (ActivityContractError, ClockPlanningError, ValueError) as exc:
            code = getattr(exc, "code", "invalid_activity_checkpoint")
            message = getattr(exc, "message", "活动检查点无法规划")
            raise SettlementValidationError(code, message) from exc

        if isinstance(self._world_state_applier, DefaultWorldStateApplier):
            projected, consumer_deltas, _ = self._world_state_applier.apply_with_facts(
                previous,
                [],
                time_plan,
            )
        else:
            projected = self._world_state_applier.apply_world_deltas(
                previous,
                [],
                time_plan,
            )
            consumer_deltas = []

        proposal = await self._adjudicator.adjudicate(
            intent,
            projected.model_copy(deep=True),
        )
        validate_adjudication_proposal(intent, projected, proposal)
        roll = roll_for_action(intent, projected)
        executor_facts = build_executor_facts(
            projected,
            requested_executor_id=proposal.requested_executor_id,
            actual_executor_id=proposal.actual_executor_id,
            execution_status=proposal.execution_status,
            action_kind=intent.action_kind,
        )
        try:
            require_available_executor(projected, activity)
        except ActivityContractError as exc:
            transition = (
                proposal.activity_decision.transition
                if proposal.activity_decision is not None
                else None
            )
            if transition not in {"pause", "await_player", "fail"}:
                raise self._activity_error(exc) from exc
        changed, world_state_attribution = apply_world_deltas_with_facts(
            projected,
            proposal.deltas,
            executor_facts=executor_facts,
            roll=roll,
        )
        settlement_id = new_settlement_id()
        version_id = new_version_id()
        combined_deltas = [*consumer_deltas, *proposal.deltas]
        try:
            changed, activity = finish_checkpoint(
                changed,
                intent=intent,
                plan=time_plan,
                proposal=proposal,
                settlement_id=settlement_id,
                result_version_id=version_id,
                committed_delta_ids=[delta.delta_id for delta in combined_deltas],
            )
        except ActivityContractError as exc:
            raise self._activity_error(exc) from exc
        validate_final_state(previous, changed)
        self._assert_head(intent)
        proposal_for_commit = proposal.model_copy(
            update={
                "deltas": combined_deltas,
                "duration_candidate": time_plan.normalized_duration.duration,
                "duration_reason": "活动检查点实际经过时间",
            },
        )
        result = worlds.commit_settlement(
            intent,
            changed,
            proposal_for_commit,
            time_plan=time_plan,
            executor_facts=executor_facts,
            world_state_attribution=world_state_attribution,
            rolls=[roll] if roll is not None else [],
            settlement_id=settlement_id,
            version_id=version_id,
            activity_id=activity.activity_id,
            checkpoint_id=checkpoint.checkpoint_id,
            checkpoint_sequence=checkpoint.sequence,
            activity_status=activity.status,
            crossed_events=[boundary.boundary_key for boundary in time_plan.boundaries],
            actual_outcome=proposal.activity_decision.reason,
        )
        committed = worlds.load_version(result.version.version_id)
        return ActionExecution(state=committed.state, result=result)

    def execute_sync(self, intent: ActionIntent) -> ActionExecution:
        return asyncio.run(self.execute(intent))

    async def continue_activity_batch(
        self,
        *,
        game_id: GameId,
        branch_id: BranchId,
        expected_parent_version_id: VersionId,
        activity_id: ActivityId,
        max_checkpoints: int = 4,
    ) -> ActivityBatchExecution:
        if isinstance(max_checkpoints, bool) or not 1 <= max_checkpoints <= 16:
            raise SettlementValidationError(
                "invalid_checkpoint_batch_limit",
                "max_checkpoints 必须是 1 到 16 的整数",
            )
        head = worlds.load_branch_head(game_id, branch_id)
        if head.ref.version_id != expected_parent_version_id:
            raise worlds.StaleParentVersionError(
                expected_parent_version_id,
                head.ref.version_id,
            )

        state = head.state
        results: list[SettlementCommitResult] = []
        for _ in range(max_checkpoints):
            try:
                _, activity = find_activity(state, activity_id)
            except ActivityContractError as exc:
                raise self._activity_error(exc) from exc
            if activity.status != "in_progress":
                break
            checkpoint = next(
                item for item in activity.checkpoints if item.status == "pending"
            )
            intent = ActionIntent(
                game_id=game_id,
                branch_id=branch_id,
                expected_parent_version_id=checkpoint.expected_parent_version_id,
                client_action_id=checkpoint.client_action_id,
                raw_text=f"自动继续活动：{activity.intent}",
                action_kind="activity_checkpoint",
                requested_executor_id=activity.requested_executor_id,
                mode="activity_auto_continue",
                activity_id=activity.activity_id,
                checkpoint_id=checkpoint.checkpoint_id,
                checkpoint_sequence=checkpoint.sequence,
                activity_command="continue",
            )
            execution = await self.execute(intent)
            state = execution.state
            results.append(execution.result)

        _, activity = find_activity(state, activity_id)
        processing = activity.status == "in_progress"
        cursor = str(activity.next_checkpoint_id) if processing else None
        return ActivityBatchExecution(
            state=state,
            activity=activity,
            results=tuple(results),
            processing=processing,
            continuation_cursor=cursor,
        )

    def continue_activity_batch_sync(self, **kwargs) -> ActivityBatchExecution:
        return asyncio.run(self.continue_activity_batch(**kwargs))
