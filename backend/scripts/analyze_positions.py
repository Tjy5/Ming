"""Analyze position coverage: which positions are vacant, which ministers lack positions."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.positions import POSITION_REGISTRY, PositionCategory, resolve_position


def main():
    data_path = Path(__file__).parent.parent / "data" / "ministers.json"
    raw = json.loads(data_path.read_text(encoding="utf-8"))

    # Parse each minister's positions using the same logic as game.py
    def split_pos(value):
        tokens = [value]
        for d in ("兼", "、", "，", ","):
            next_t = []
            for t in tokens:
                next_t.extend(t.split(d))
            tokens = next_t
        return [t.strip() for t in tokens if t.strip()]

    ministers = []
    for item in raw:
        name = item["name"]
        pos_text = item.get("position", "")
        raw_positions = split_pos(pos_text) if pos_text else []
        resolved = []
        unresolved = []
        for p in raw_positions:
            c = resolve_position(p)
            if c:
                if c not in resolved:
                    resolved.append(c)
            else:
                unresolved.append(p)
        ministers.append({
            "name": name,
            "faction": item.get("faction", ""),
            "position_text": pos_text,
            "resolved": resolved,
            "unresolved": unresolved,
            "canonical_position": item.get("canonical_position", ""),
            "is_eunuch": item.get("is_eunuch", False),
            "entry_year": item.get("entry_year", 1627),
            "entry_month": item.get("entry_month", 8),
        })

    print(f"== 大臣总数: {len(ministers)} ==\n")

    # Ministers with no resolved positions
    no_pos = [m for m in ministers if not m["resolved"]]
    print(f"== 无有效官职的大臣 ({len(no_pos)}) ==")
    for m in no_pos:
        print(f"  {m['name']} ({m['faction']}) - position文本: '{m['position_text']}' unresolved: {m['unresolved']}")

    print()

    # Position holders map
    holders = {}  # position -> list of minister names
    for m in ministers:
        for p in m["resolved"]:
            holders.setdefault(p, []).append(m["name"])

    # All positions in registry
    print("== 官职注册表覆盖情况 ==\n")
    for cat in PositionCategory:
        positions = [(n, i) for n, i in POSITION_REGISTRY.items() if i.category == cat]
        print(f"--- {cat.value} ({len(positions)} 职位) ---")
        for pos_name, pos_info in positions:
            h = holders.get(pos_name, [])
            unique_mark = "🔒" if pos_info.unique else "  "
            if not h:
                status = "❌ 空缺"
            elif pos_info.unique and len(h) > 1:
                status = f"⚠️ 冲突: {', '.join(h)}"
            else:
                status = f"✅ {', '.join(h)}"
            print(f"  {unique_mark} {pos_name} (w={pos_info.weight}): {status}")
        print()

    # Summary
    all_unique = [n for n, i in POSITION_REGISTRY.items() if i.unique]
    vacant_unique = [n for n in all_unique if n not in holders]
    conflict_unique = [n for n in all_unique if len(holders.get(n, [])) > 1]

    all_non_unique = [n for n, i in POSITION_REGISTRY.items() if not i.unique]
    vacant_non_unique = [n for n in all_non_unique if n not in holders]

    print(f"\n== 统计汇总 ==")
    print(f"  注册表总职位数: {len(POSITION_REGISTRY)}")
    print(f"  唯一职位: {len(all_unique)}, 空缺: {len(vacant_unique)}, 冲突: {len(conflict_unique)}")
    print(f"  非唯一职位: {len(all_non_unique)}, 无人担任: {len(vacant_non_unique)}")
    print(f"\n  空缺唯一职位列表:")
    for v in vacant_unique:
        print(f"    - {v}")
    if conflict_unique:
        print(f"\n  冲突唯一职位列表:")
        for c in conflict_unique:
            print(f"    - {c}: {holders[c]}")
    if vacant_non_unique:
        print(f"\n  无人担任的非唯一职位:")
        for v in vacant_non_unique:
            print(f"    - {v}")


if __name__ == "__main__":
    import io, sys
    out = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = out
    main()
    sys.stdout = old_stdout
    report = out.getvalue()
    report_path = Path(__file__).parent / "position_report.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"Report written to {report_path}")
