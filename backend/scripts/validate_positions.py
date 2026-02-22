"""Validate all positions in ministers.json exist in PositionRegistry."""

import json
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.positions import resolve_position, POSITION_REGISTRY


def validate_ministers():
    """Check all positions in ministers.json are valid."""
    data_path = Path(__file__).parent.parent / "data" / "ministers.json"
    raw = json.loads(data_path.read_text(encoding="utf-8"))

    errors = []
    warnings = []

    for item in raw:
        name = item.get("name", "<unknown>")

        # Check positions field
        positions = item.get("positions")
        if positions is None:
            # Legacy format - check position field
            pos_str = item.get("position", "")
            if pos_str:
                for delimiter in ("兼", "、", "，", ","):
                    pos_str = pos_str.replace(delimiter, "|")
                for token in pos_str.split("|"):
                    token = token.strip()
                    if token and resolve_position(token) is None:
                        errors.append(f"{name}: invalid position '{token}'")
        else:
            if not isinstance(positions, list):
                errors.append(f"{name}: positions is not a list")
            else:
                for pos in positions:
                    if not isinstance(pos, str):
                        errors.append(f"{name}: position is not a string: {pos!r}")
                    elif resolve_position(pos) is None:
                        errors.append(f"{name}: invalid position '{pos}'")

        # Check is_eunuch for EUNUCH positions
        is_eunuch = item.get("is_eunuch", False)
        pos_str = item.get("position", "") or ""
        eunuch_keywords = ["司礼监", "太监", "秉笔", "掌印"]
        has_eunuch_pos = any(kw in pos_str for kw in eunuch_keywords)
        if has_eunuch_pos and not is_eunuch:
            warnings.append(f"{name}: has eunuch position but is_eunuch=false")

    return errors, warnings


if __name__ == "__main__":
    print(f"Position Registry: {len(POSITION_REGISTRY)} positions defined")
    print()

    errors, warnings = validate_ministers()

    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  ⚠ {w}")
        print()

    if errors:
        print(f"Errors ({len(errors)}):")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print("✓ All positions valid")
        sys.exit(0)
