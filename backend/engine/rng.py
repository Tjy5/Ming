"""Stable, versioned random material for explicit public gameplay rolls."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from models.game import GameState
from models.settlement import ActionIntent
from models.world_state import RollRecord, UncertaintyReason


RNG_PROTOCOL_VERSION = "world-state-rng-v1"
HIGH_UNCERTAINTY_ACTIONS: dict[str, UncertaintyReason] = {
    "warfare": "opposition",
    "infiltration": "hidden_information",
    "escape": "hazard",
}


def _canonical_bytes(domain: str, fields: Iterable[object]) -> bytes:
    payload = {
        "domain": domain,
        "protocol": RNG_PROTOCOL_VERSION,
        "fields": [str(field) for field in fields],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def stable_digest(domain: str, *fields: object) -> bytes:
    return hashlib.sha256(_canonical_bytes(domain, fields)).digest()


def stable_seed(domain: str, *fields: object) -> int:
    return int.from_bytes(stable_digest(domain, *fields)[:8], "big", signed=False)


def stable_d100(domain: str, *fields: object) -> int:
    """Map SHA-256 material to D100 without modulo bias."""

    counter = 0
    while True:
        material = stable_digest(domain, *fields, counter)
        for byte in material:
            if byte < 200:
                return (byte % 100) + 1
        counter += 1


def roll_for_action(intent: ActionIntent, state: GameState) -> RollRecord | None:
    """Create the one public roll for a server-recognized uncertain action.

    Historical deviation and prose alone never trigger a roll. The record is a
    pure projection of durable action/branch/parent identities, so retries and
    independent processes produce the same value and roll id.
    """

    reason = HIGH_UNCERTAINTY_ACTIONS.get(intent.action_kind or "")
    if reason is None:
        return None
    fact_references = [
        f"parent_version:{intent.expected_parent_version_id}",
        *(f"target_entity:{entity_id}" for entity_id in intent.target_entity_ids),
    ]
    if intent.target_region_id is not None:
        fact_references.append(f"target_region:{intent.target_region_id}")
    slot = str(intent.checkpoint_id or "action")
    identity = (
        intent.game_id,
        intent.branch_id,
        intent.expected_parent_version_id,
        intent.client_action_id,
        slot,
        reason,
        state.time.clock.absolute_hour if state.time.clock is not None else 0,
    )
    roll_id = stable_digest("roll-id", *identity).hex()
    return RollRecord(
        roll_id=roll_id,
        protocol_version=RNG_PROTOCOL_VERSION,
        raw_d100=stable_d100("d100", *identity),
        uncertainty_reasons=[reason],
        fact_references=fact_references,
        checkpoint_slot=slot,
    )

