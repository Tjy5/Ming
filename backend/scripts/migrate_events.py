from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.scripts import SCRIPT_REGISTRY, ScriptEvent


ROOT = Path(__file__).resolve().parents[1]
EVENTS_DIR = ROOT / "data" / "events"


CONDITION_BY_SCRIPT_ID: dict[str, dict | None] = {
    "qian-jiazheng-impeachment-1627-10": {
        "type": "minister_alive",
        "name": "魏忠贤",
    },
    "post-wei-vacuum-1627-10": {
        "type": "minister_removed",
        "name": "魏忠贤",
    },
    "wei-zhongxian-falls-1627-11": {
        "type": "minister_alive",
        "name": "魏忠贤",
    },
    "post-wei-remnant-settlement-1627-11": {
        "type": "minister_removed",
        "name": "魏忠贤",
    },
    "yuan-chonghuan-arrest": {
        "type": "and",
        "conditions": [
            {"type": "script_resolved", "script_id": "jisi-invasion"},
            {"type": "minister_alive", "name": "袁崇焕"},
        ],
    },
    "liaodong-command-vacancy-1629-12": {
        "type": "and",
        "conditions": [
            {"type": "script_resolved", "script_id": "jisi-invasion"},
            {"type": "minister_removed", "name": "袁崇焕"},
        ],
    },
    "li-zicheng-joins": {
        "type": "region_field_lt",
        "region": "陕西",
        "field": "stability",
        "value": 30,
    },
    "sun-chengzong-recovery": {
        "type": "and",
        "conditions": [
            {"type": "minister_active", "name": "孙承宗"},
            {"type": "state_field_gt", "field": "military_strength", "value": 20},
        ],
    },
    "dalinghe-prelude": {
        "type": "region_field_lt",
        "region": "辽东",
        "field": "stability",
        "value": 40,
    },
}


def _decree_to_dict(decree) -> dict:
    payload = {"type": decree.type.value}
    if decree.target is not None:
        payload["target"] = decree.target
    if decree.sub_action is not None:
        payload["sub_action"] = decree.sub_action.value
    if decree.parameters:
        payload["parameters"] = decree.parameters
    return payload


def _event_to_dict(event: ScriptEvent) -> dict:
    condition = CONDITION_BY_SCRIPT_ID.get(event.script_id)
    return {
        "script_id": event.script_id,
        "trigger_year": event.trigger_year,
        "trigger_month": event.trigger_month,
        "title": event.title,
        "is_blocking": event.is_blocking,
        "rich_description": event.rich_description,
        "historical_hint": event.historical_hint,
        "condition": condition,
        "choices": [
            {
                "label": choice.label,
                "description": choice.description,
                "decrees": [_decree_to_dict(d) for d in choice.decrees],
                "loyalty_effects": [[name, delta] for name, delta in choice.loyalty_effects],
                "state_effects": dict(choice.state_effects),
            }
            for choice in event.choices
        ],
    }


def _write_events(*, clean: bool) -> int:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    if clean:
        for file in EVENTS_DIR.glob("*.json"):
            file.unlink()

    events = sorted(
        SCRIPT_REGISTRY.values(),
        key=lambda item: (item.trigger_year, item.trigger_month, item.script_id),
    )
    for event in events:
        output = EVENTS_DIR / f"{event.script_id}.json"
        output.write_text(
            json.dumps(_event_to_dict(event), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return len(events)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate hardcoded script events to backend/data/events/*.json")
    parser.add_argument("--clean", action="store_true", help="Remove existing json files before writing")
    args = parser.parse_args()

    written = _write_events(clean=args.clean)
    print(f"Wrote {written} script event files to {EVENTS_DIR}")


if __name__ == "__main__":
    main()

