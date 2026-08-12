"""Empty-roster continuity orchestration for governance API entry points.

When a committed world loses every governance-capable actor, entry points call
``ensure_governance_continuity`` before their own settlement. The power-vacuum
facts and derived replacement actors are committed as exactly one settlement
and one immutable version through the standard transaction owner; the published
head cache is then refreshed so the caller continues on the post-continuity
world. Legacy pre-root states keep their legacy fallback and return ``None``.
"""

from __future__ import annotations

from db import worlds
from api.action_service import DefaultTimePlanner, DefaultWorldStateApplier
from api.state import _get_world_head_ref, _publish_world_head
from engine.activity import ActivityContractError, rebase_pending_checkpoints
from engine.continuity import (
    GOVERNANCE_CONTINUITY_ACTION_KIND,
    build_continuity_proposal,
    detect_governance_vacuum,
)
from engine.elapsed_consumers import default_clock_registry
from engine.execution import build_executor_facts
from engine.lifecycle import DefaultLifecyclePlanner
from engine.settlement import (
    SettlementValidationError,
    apply_world_deltas,
    validate_adjudication_proposal,
    validate_final_state,
)
from models.game import GameState
from models.settlement import ActionIntent
from models.world import new_client_action_id, new_settlement_id, new_version_id


def ensure_governance_continuity() -> GameState | None:
    """Commit one continuity settlement when no capable actor remains.

    Returns the published post-continuity head state, or ``None`` when the
    current head has no durable world root, is terminal, or still has at
    least one assembly-capable actor.
    """

    ref = _get_world_head_ref()
    if ref is None:
        return None
    previous = worlds.load_branch_head(ref.game_id, ref.branch_id).state
    if previous.player_world_status.life_status == "dead":
        return None
    if not detect_governance_vacuum(previous):
        return None

    settlement_id = new_settlement_id()
    version_id = new_version_id()
    intent = ActionIntent(
        game_id=ref.game_id,
        branch_id=ref.branch_id,
        expected_parent_version_id=ref.version_id,
        client_action_id=new_client_action_id(),
        raw_text="权力真空接替：临时治理主体登场",
        action_kind=GOVERNANCE_CONTINUITY_ACTION_KIND,
        mode=previous.phase,
    )
    proposal = build_continuity_proposal(
        previous,
        settlement_id=settlement_id,
        version_id=version_id,
    )
    validate_adjudication_proposal(intent, previous, proposal)

    registry = default_clock_registry()
    time_plan = DefaultTimePlanner(registry).plan_segment(intent, previous, proposal)
    executor_facts = build_executor_facts(
        previous,
        requested_executor_id=None,
        actual_executor_id=None,
        execution_status=proposal.execution_status,
        action_kind=intent.action_kind,
    )
    changed, consumer_deltas, world_state_attribution = DefaultWorldStateApplier(
        registry,
    ).apply_with_facts(
        previous,
        proposal.deltas,
        time_plan,
        executor_facts=executor_facts,
    )
    if consumer_deltas:
        proposal = proposal.model_copy(
            update={"deltas": [*proposal.deltas, *consumer_deltas]},
        )
    lifecycle = DefaultLifecyclePlanner().propose(
        previous=previous.model_copy(deep=True),
        changed=changed.model_copy(deep=True),
    )
    if lifecycle.deltas:
        changed = apply_world_deltas(changed, list(lifecycle.deltas))
        proposal = proposal.model_copy(
            update={"deltas": [*proposal.deltas, *lifecycle.deltas]},
        )
    validate_final_state(previous, changed)

    # No provider call happens above, but the head can still move under us in
    # another request; commit_settlement performs the final CAS regardless.
    current = worlds.get_branch_head(ref.game_id, ref.branch_id)
    if current.version_id != ref.version_id:
        raise worlds.StaleParentVersionError(ref.version_id, current.version_id)
    try:
        changed = rebase_pending_checkpoints(changed, version_id)
    except ActivityContractError as exc:
        raise SettlementValidationError(exc.code, exc.message) from exc

    try:
        result = worlds.commit_settlement(
            intent,
            changed,
            proposal,
            time_plan=time_plan,
            executor_facts=executor_facts,
            world_state_attribution=world_state_attribution,
            settlement_id=settlement_id,
            version_id=version_id,
            actual_outcome="governance_continuity",
        )
    except worlds.StaleParentVersionError:
        # A concurrent continuity settlement resolved the vacuum first.
        reloaded = worlds.load_branch_head(ref.game_id, ref.branch_id)
        if detect_governance_vacuum(reloaded.state):
            raise
        _publish_world_head(reloaded.state, reloaded.ref)
        return reloaded.state

    committed = worlds.load_version(result.version.version_id)
    _publish_world_head(committed.state, committed.ref)
    return committed.state
