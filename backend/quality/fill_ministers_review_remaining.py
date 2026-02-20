# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

REVIEW_PATH = Path(__file__).resolve().parents[1] / "data" / "ministers_review.json"
REVIEW_DATE = "2026-02-20"

COMMON_SOURCES = [
    {
        "title": "《明史》总目（维基文库）",
        "url": "https://zh.wikisource.org/wiki/%E6%98%8E%E5%8F%B2",
        "tier": "A_PRIMARY",
        "locator": "全书卷目索引，待补各人物具体卷次",
    },
    {
        "title": "《明史/卷72（職官一）》",
        "url": "https://zh.wikisource.org/wiki/%E6%98%8E%E5%8F%B2/%E5%8D%B772",
        "tier": "A_PRIMARY",
        "locator": "官职名称与机构口径校验",
    },
    {
        "title": "China Biographical Database Project (CBDB) 首页",
        "url": "https://cbdb.hsites.harvard.edu/",
        "tier": "B_DATABASE",
        "locator": "人物生平与仕历待逐条核定",
    },
    {
        "title": "项目初始大臣数据（ministers.json）",
        "url": "backend/data/ministers.json",
        "tier": "C_SECONDARY",
        "locator": "当前项目设定基线",
    },
]

EVENTS_BY_FACTION = {
    "东林党": ["崇祯初东林复起", "明末党争与言路政治"],
    "阉党残余": ["崇祯初阉党清算", "内廷权力重组"],
    "勋贵集团": ["京营与勋贵政治", "甲申之变前后朝局动荡"],
    "辽东边将": ["辽东防务", "己巳之变及后续边患"],
    "中原剿匪系": ["中原流寇战事", "剿抚路线争议"],
    "温体仁派": ["崇祯中期内阁博弈", "党争与铨选"],
    "周延儒派": ["崇祯后期内阁更替", "甲申前后中枢决策"],
    "中立派": ["崇祯朝中枢与地方治理", "甲申前后政局震荡"],
}

ROLE_BY_FACTION = {
    "东林党": "清议与文官路线角色，影响士林声望与朝堂议政风向。",
    "阉党残余": "高风险旧势力角色，影响内廷稳定与清算事件链。",
    "勋贵集团": "军政资源型角色，影响京营执行与皇亲勋贵态度。",
    "辽东边将": "边防作战角色，影响辽东战线强度与边患压力。",
    "中原剿匪系": "剿寇统帅角色，影响中原战线与军费消耗。",
    "温体仁派": "中枢权术角色，影响内阁控制力与党争强度。",
    "周延儒派": "后期中枢博弈角色，影响政策执行与信誉波动。",
    "中立派": "平衡执行角色，影响跨派协同与政务稳定。",
}


def _build_contributions(note: str) -> list[str]:
    clean_note = (note or "").strip()
    if clean_note:
        return [
            f"依据项目基线记载：{clean_note}",
            "在本项目中作为可交互历史角色，参与明末关键政务或战事决策。",
        ]
    return [
        "在项目设定中承担明末历史角色，参与朝局或战局发展。",
        "其行为会对派系关系与事件链产生影响。",
    ]


def main() -> int:
    rows = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    updated = 0
    for row in rows:
        review = row.get("review", {})
        if review.get("status") != "pending":
            continue

        base = row.get("base_profile", {})
        faction = base.get("faction", "")
        position = (base.get("position") or "").strip()
        note = base.get("historical_note") or ""

        office_history = []
        if position:
            office_history.append(position)
        office_history.append("明末政局参与者（项目设定）")

        row["aliases"] = row.get("aliases", []) if isinstance(row.get("aliases"), list) else []
        row["birth_year"] = None
        row["death_year"] = None
        row["office_history"] = office_history
        row["major_contributions"] = _build_contributions(note)
        row["related_events"] = EVENTS_BY_FACTION.get(
            faction, ["崇祯朝政局演变", "明末危机事件链"]
        )
        row["project_role_background"] = ROLE_BY_FACTION.get(
            faction, "明末历史角色，影响事件推进与派系互动。"
        )
        row["sources"] = COMMON_SOURCES
        row["review"] = {
            "status": "in_review",
            "reviewer": "codex",
            "last_reviewed_on": REVIEW_DATE,
            "notes": "已按批处理补全审查字段；待补《明史》具体卷次与逐条生卒年核定。",
        }
        updated += 1

    REVIEW_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {updated} pending entries in {REVIEW_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
