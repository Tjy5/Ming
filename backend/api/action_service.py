from __future__ import annotations

import asyncio
import json
import threading
import weakref
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException
from pydantic import ValidationError

from db import worlds
from engine.settlement import (
    SettlementValidationError,
    apply_world_deltas,
    validate_adjudication_proposal,
    validate_final_state,
)
from models.game import GameState
from models.settlement import (
    ActionIntent,
    AdjudicationProposal,
    ProviderAttribution,
    SettlementCommitResult,
    WorldDelta,
)


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
    ) -> object | None: ...


class ActionWorldStateApplier(Protocol):
    def apply_world_deltas(
        self,
        state: GameState,
        deltas: list[WorldDelta],
        time_plan: object | None,
    ) -> GameState: ...


@dataclass(frozen=True)
class ActionExecution:
    state: GameState
    result: SettlementCommitResult


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


class DefaultWorldStateApplier:
    def apply_world_deltas(
        self,
        state: GameState,
        deltas: list[WorldDelta],
        time_plan: object | None,
    ) -> GameState:
        if time_plan is not None:
            raise SettlementValidationError(
                "time_contract_unavailable",
                "默认 world-state applier 不接受未消费的 time plan",
            )
        return apply_world_deltas(state, deltas)


class AIActionAdjudicator:
    """Strict JSON adjudication using exactly one provider call.

    Provider/schema failures remain pre-commit errors. This adapter never calls
    a rule parser, retry loop, narrative template, or fallback adjudicator.
    """

    def __init__(self, provider_loader):
        self._provider_loader = provider_loader

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
        prompt = (
            "Return exactly one JSON object matching AdjudicationProposal schema_version=1. "
            "Judge the player's action only from the supplied current-world snapshot. "
            "Do not use historical canon as a whitelist and do not include prose outside JSON.\n"
            f"ACTION_INTENT={intent.model_dump_json()}\n"
            f"CURRENT_WORLD={state.model_dump_json()}"
        )
        try:
            generated = await provider.generate_text_once(
                prompt,
                system_prompt=(
                    "You are the action adjudicator for an open sandbox. Output strict JSON only."
                ),
                max_output_tokens=4096,
                response_json=True,
            )
        except Exception as exc:
            raise ActionAdjudicationError(
                "adjudication_provider_error",
                "AI 裁决调用失败，世界状态未提交",
            ) from exc

        try:
            raw = json.loads(generated.text)
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
    ) -> None:
        self._adjudicator = adjudicator
        self._time_planner = time_planner or NoopTimePlanner()
        self._world_state_applier = world_state_applier or DefaultWorldStateApplier()
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

        proposal = await self._adjudicator.adjudicate(intent, previous.model_copy(deep=True))
        validate_adjudication_proposal(intent, previous, proposal)
        time_plan = self._time_planner.plan_segment(intent, previous, proposal)
        changed = self._world_state_applier.apply_world_deltas(
            previous,
            proposal.deltas,
            time_plan,
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

        result = worlds.commit_settlement(intent, changed, proposal)
        committed = worlds.load_version(result.version.version_id)
        return ActionExecution(state=committed.state, result=result)

    def execute_sync(self, intent: ActionIntent) -> ActionExecution:
        return asyncio.run(self.execute(intent))
