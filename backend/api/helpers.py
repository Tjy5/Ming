from __future__ import annotations

from models.game import GameState


def apply_state_effects(state: GameState, effects: dict[str, int]) -> None:
    for key, delta in effects.items():
        parts = key.split(".")
        if parts[0] == "global" and len(parts) == 2:
            obj, field = state, parts[1]
        elif parts[0] == "region" and len(parts) == 3:
            obj = next((r for r in state.regions if r.name == parts[1]), None)
            field = parts[2]
        elif parts[0] == "faction" and len(parts) == 3:
            obj = next((f for f in state.factions if f.name == parts[1]), None)
            field = parts[2]
        else:
            continue
        if obj is not None and hasattr(obj, field):
            current = getattr(obj, field)
            if isinstance(current, (int, float)):
                setattr(obj, field, current + delta)


def apply_loyalty_effects(state: GameState, effects: list[tuple[str, int]]) -> None:
    for name, delta in effects:
        minister = next((m for m in state.ministers if m.name == name), None)
        if minister is not None:
            minister.loyalty += delta

