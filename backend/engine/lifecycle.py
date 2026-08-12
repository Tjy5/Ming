"""Pure lifecycle projection contract consumed by the sandbox settlement flow.

The lifecycle sibling derives presentation mode/goals from committed facts.  It
never writes the database or mutates a ``GameState`` in place; callers may turn
the returned typed proposal into validated lifecycle deltas in the same
settlement as the originating action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from models.game import GameState
from models.settlement import LifecycleWorldDelta
from models.world import new_delta_id


@dataclass(frozen=True)
class LifecycleState:
    mode: str
    goal_ids: tuple[str, ...]
    transition_reason: str
    source_version_id: str | None = None


@dataclass(frozen=True)
class LifecycleDeltaProposal:
    deltas: tuple[LifecycleWorldDelta, ...] = ()
    projection: LifecycleState | None = None


class LifecyclePlanner(Protocol):
    def propose(self, *, previous: GameState, changed: GameState) -> LifecycleDeltaProposal: ...


class DefaultLifecyclePlanner:
    """Minimal fact-derived continuity fallback.

    Existing chapter/phase fields remain a compatibility projection.  A living
    player with no goals receives a typed continuity opportunity; terminal
    players receive no new transition.
    """

    def propose(self, *, previous: GameState, changed: GameState) -> LifecycleDeltaProposal:
        del previous
        status = changed.player_world_status
        if status.life_status == "dead":
            return LifecycleDeltaProposal()
        if status.actionable_goal_ids:
            mode = "governance" if changed.phase == "governance" else "life_story"
            return LifecycleDeltaProposal(
                projection=LifecycleState(mode, tuple(status.actionable_goal_ids), "committed_world_facts")
            )
        goal_id = "world_continuity_required"
        delta = LifecycleWorldDelta(
            delta_id=new_delta_id(),
            transition_type="goal",
            transition_id=goal_id,
            before_status=None,
            next_status="available",
            source_proposal="lifecycle:continuity-fallback",
        )
        return LifecycleDeltaProposal(
            deltas=(delta,),
            projection=LifecycleState(
                "survival"
                if status.regime_status != "governing"
                else ("governance" if changed.phase == "governance" else "life_story"),
                (goal_id,),
                "no_actionable_goal",
            ),
        )
