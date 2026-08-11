from __future__ import annotations

from engine.execution_loss import apply_execution_loss, execution_loss_factor
from models.enums import MinisterStatus
from models.game import GameState, Minister, MinisterAbilities
from trpg.writeback import apply_state_changes


def _minister(name: str, civil: int, loyalty: int, corruption: int) -> Minister:
    return Minister(
        name=name,
        faction="test",
        abilities=MinisterAbilities(civil=civil),
        loyalty=loyalty,
        corruption=corruption,
        status=MinisterStatus.ACTIVE,
        positions=["中书省左丞相"],
    )


def test_legacy_adapter_never_averages_unrelated_ministers():
    state = GameState(
        ministers=[
            _minister("能臣", 100, 100, 0),
            _minister("庸臣", 0, 5, 95),
        ],
    )
    no_actor = apply_execution_loss(state, {"national_treasury": 100})
    high = apply_execution_loss(state, {"national_treasury": 100}, executor_name="能臣")
    low = apply_execution_loss(state, {"national_treasury": 100}, executor_name="庸臣")

    assert no_actor["national_treasury"] == 100
    assert high["national_treasury"] > low["national_treasury"]
    assert execution_loss_factor(state, "不存在") == 0


def test_trpg_uses_the_same_actual_executor_factor():
    state = GameState(ministers=[_minister("能臣", 100, 100, 0)])
    before = state.national_treasury
    expected_delta = apply_execution_loss(
        state,
        {"national_treasury": 10},
        executor_name="能臣",
        action_kind="governance",
    )["national_treasury"]
    result = apply_state_changes(
        state,
        {"global.national_treasury": 10},
        executor_name="能臣",
    )
    assert result["applied"] == ["global.national_treasury"]
    assert 0 < expected_delta < 10
    assert state.national_treasury == before + expected_delta
