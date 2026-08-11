from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from api.action_service import ActionService
from db import saves, worlds
from engine.calendar import ensure_game_time_clock, normalize_duration
from engine.settlement import SettlementValidationError, apply_world_deltas
from models.game import create_initial_state
from models.settlement import (
    ActionIntent,
    AdjudicationProposal,
    CommitmentWorldDelta,
    MetricWorldDelta,
)
from models.world import DeltaId, Duration, new_client_action_id
from models.world_state import CommitmentRecord, MetricTarget


def _commitment(state, commitment_id: str = "tax-receipt") -> CommitmentRecord:
    start = ensure_game_time_clock(state.time)
    due_at = normalize_duration(start, Duration(unit="day", value=1)).end
    return CommitmentRecord(
        commitment_id=commitment_id,
        target=MetricTarget(target_scope="world", metric_key="national_treasury"),
        amount=Decimal("25"),
        source_kind="policy",
        source_ref="policy:tax-reform",
        due_at=due_at,
    )


class _TwelveHourAdjudicator:
    async def adjudicate(self, _intent, _state):
        return AdjudicationProposal(
            result_tier="success",
            execution_status="completed",
            duration_candidate=Duration(unit="hour", value=12),
            duration_reason="等待半日",
        )


def test_commitment_applies_once_when_elapsed_time_reaches_due_at(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "commitments.db")
    saves.init_db()
    state = create_initial_state()
    record = _commitment(state)
    state.world_state.commitments[record.commitment_id] = record
    before = state.national_treasury
    root = worlds.create_game_with_root(state)
    service = ActionService(adjudicator=_TwelveHourAdjudicator())

    first_intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="等待半日",
        action_kind="wait",
    )
    first = service.execute_sync(first_intent)
    assert first.state.national_treasury == before
    assert first.state.world_state.commitments[record.commitment_id].status == "pending"

    second_intent = first_intent.model_copy(
        update={
            "expected_parent_version_id": first.result.version.version_id,
            "client_action_id": new_client_action_id(),
        },
    )
    second = service.execute_sync(second_intent)
    replayed = service.execute_sync(second_intent)

    assert second.state.national_treasury == before + 25
    assert second.state.world_state.commitments[record.commitment_id].status == "applied"
    assert any(isinstance(delta, MetricWorldDelta) for delta in second.result.facts.deltas)
    assert any(isinstance(delta, CommitmentWorldDelta) for delta in second.result.facts.deltas)
    assert replayed.result.replayed is True
    assert replayed.state == second.state


def test_commitment_transition_is_typed_and_cannot_repeat():
    state = create_initial_state()
    record = _commitment(state)
    created = apply_world_deltas(
        state,
        [
            CommitmentWorldDelta(
                delta_id=DeltaId(uuid4()),
                operation="create",
                commitment_id=record.commitment_id,
                record=record,
            ),
        ],
    )
    cancelled = apply_world_deltas(
        created,
        [
            CommitmentWorldDelta(
                delta_id=DeltaId(uuid4()),
                operation="cancel",
                commitment_id=record.commitment_id,
                before_status="pending",
                transitioned_at=ensure_game_time_clock(created.time),
            ),
        ],
    )
    assert cancelled.world_state.commitments[record.commitment_id].status == "cancelled"

    with pytest.raises(SettlementValidationError) as exc:
        apply_world_deltas(
            cancelled,
            [
                CommitmentWorldDelta(
                    delta_id=DeltaId(uuid4()),
                    operation="cancel",
                    commitment_id=record.commitment_id,
                    transitioned_at=ensure_game_time_clock(cancelled.time),
                ),
            ],
        )
    assert exc.value.code == "delta_precondition_failed"
