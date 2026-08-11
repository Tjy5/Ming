"""Deterministic governance benchmark with named, non-compensating checks."""

from __future__ import annotations

import json

from engine.core import DECREE_EFFECTS, process_decree
from engine.state_consistency import validate_narrative_text
from models.enums import DecreeType
from models.game import FreeformResult, GameState, StructuredDecree


CASES = [
    {"id": "tax_decrease", "decree": StructuredDecree(type=DecreeType.TAX_DECREASE)},
    {"id": "tax_increase", "decree": StructuredDecree(type=DecreeType.TAX_INCREASE)},
    {"id": "recruit_troops", "decree": StructuredDecree(type=DecreeType.RECRUIT_TROOPS)},
    {"id": "disband_troops", "decree": StructuredDecree(type=DecreeType.DISBAND_TROOPS)},
    {"id": "disaster_relief", "decree": StructuredDecree(type=DecreeType.DISASTER_RELIEF)},
    {"id": "diplomacy", "decree": StructuredDecree(type=DecreeType.DIPLOMACY)},
    {"id": "harsh_punishment", "decree": StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)},
    {
        "id": "freeform_tax",
        "freeform": FreeformResult(
            effects={"global.national_treasury": -200, "global.civil_morale": 50},
            narrative="府库支出与民心变化已经按本次结算记录。",
        ),
    },
    {
        "id": "freeform_personnel",
        "freeform": FreeformResult(
            effects={"global.court_prestige": 30},
            narrative="军府威望依照本次结算发生变化。",
        ),
    },
]


def _make_state() -> GameState:
    from tests.test_freeform import make_state

    return make_state()


def _direction_ok(case: dict, before: GameState, after: GameState) -> bool:
    if "decree" not in case:
        effects = case["freeform"].effects
        expected = {path.split(".")[1]: value for path, value in effects.items()}
    else:
        expected = DECREE_EFFECTS[case["decree"].type]
    for field, target in expected.items():
        if not isinstance(target, (int, float)) or target == 0:
            continue
        changed = getattr(after, field) - getattr(before, field)
        if (target > 0 and changed < 0) or (target < 0 and changed > 0):
            return False
    return True


def test_benchmark_named_cases_all_pass_and_use_narrative_validator(tmp_path):
    results: list[dict[str, object]] = []
    for case in CASES:
        before = _make_state()
        after = before.model_copy(deep=True)
        if "decree" in case:
            process_decree(after, decree=case["decree"])
            narrative = f"本次政令已经结算，当前国库为{after.national_treasury}。"
        else:
            process_decree(after, freeform=case["freeform"])
            narrative = case["freeform"].narrative
        validator_issues = validate_narrative_text(narrative, after)
        checks = {
            "direction": _direction_ok(case, before, after),
            "bounds": GameState.model_validate(after.model_dump()) == after,
            "tracking": len(after.active_policies) == len(before.active_policies),
            "narrative_validator": not validator_issues,
        }
        results.append({"case_id": case["id"], "checks": checks})
        assert all(checks.values()), f"{case['id']} failed named checks: {checks}"

    artifact = tmp_path / "world-state-benchmark.json"
    artifact.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    assert artifact.is_file()
