from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from ai.fallbacks import rule_minister_dialogue
from engine.rng import roll_for_action, stable_d100, stable_seed
from models.game import GameState, Minister
from models.settlement import ActionIntent
from models.world import BranchId, ClientActionId, GameId, VersionId


def _intent(action_kind: str = "warfare") -> ActionIntent:
    return ActionIntent(
        game_id=GameId(UUID("00000000-0000-0000-0000-000000000001")),
        branch_id=BranchId(UUID("00000000-0000-0000-0000-000000000002")),
        expected_parent_version_id=VersionId(UUID("00000000-0000-0000-0000-000000000003")),
        client_action_id=ClientActionId(UUID("00000000-0000-0000-0000-000000000004")),
        raw_text="出兵迎战",
        action_kind=action_kind,
    )


def test_stable_seed_and_d100_do_not_use_python_hash():
    assert stable_seed("case", "alpha", 1) == stable_seed("case", "alpha", 1)
    assert 1 <= stable_d100("case", "alpha", 1) <= 100


def test_stable_seed_matches_independent_processes_with_different_hash_seeds():
    backend = Path(__file__).resolve().parents[1]
    code = "from engine.rng import stable_seed; print(stable_seed('case','alpha',1))"
    outputs = []
    for hash_seed in ("1", "999"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = hash_seed
        outputs.append(
            subprocess.check_output(
                [sys.executable, "-c", code],
                cwd=backend,
                env=env,
                text=True,
            ).strip(),
        )
    assert outputs[0] == outputs[1]


def test_only_named_high_uncertainty_actions_receive_one_public_roll():
    state = GameState()
    first = roll_for_action(_intent(), state)
    retry = roll_for_action(_intent(), state)
    assert first == retry
    assert first is not None
    assert first.uncertainty_reasons == ["opposition"]
    assert roll_for_action(_intent("governance"), state) is None


def test_rule_dialogue_fallback_has_no_hidden_random_loyalty_change():
    minister = Minister(name="测试大臣", faction="测试派系")
    state = GameState(ministers=[minister])

    first = rule_minister_dialogue(minister, "请陈述方略", state, [])
    second = rule_minister_dialogue(minister, "请陈述方略", state, [])

    assert first == second
    assert first["loyalty_change"] == 0
    assert first["mood"] == "neutral"
