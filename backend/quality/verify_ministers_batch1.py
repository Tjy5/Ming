# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

REVIEW_PATH = Path(__file__).resolve().parents[1] / "data" / "ministers_review.json"
REVIEW_DATE = "2026-02-20"

# Derived from MediaWiki API search + parse(section) matching.
MAPPING = {
    "韩爌": {"volume": 240, "section": "韓爌", "verified": True},
    "钱谦益": {"volume": 70, "section": None, "verified": False},
    "钱龙锡": {"volume": 251, "section": "錢龍錫", "verified": True},
    "成基命": {"volume": 251, "section": "成基命", "verified": True},
    "文震孟": {"volume": 251, "section": "文震孟", "verified": True},
    "黄道周": {"volume": 24, "section": None, "verified": False},
    "刘宗周": {"volume": 232, "section": None, "verified": False},
    "倪元璐": {"volume": 70, "section": None, "verified": False},
    "范景文": {"volume": 24, "section": None, "verified": False},
    "史可法": {"volume": 274, "section": "史可法", "verified": True},
    "姜曰广": {"volume": 274, "section": "姜曰廣", "verified": True},
    "高弘图": {"volume": 274, "section": "高弘圖", "verified": True},
    "马世奇": {"volume": 99, "section": None, "verified": False},
    "吴甡": {"volume": 252, "section": "吳甡", "verified": True},
    "瞿式耜": {"volume": 280, "section": "瞿式耜", "verified": True},
    "魏忠贤": {"volume": 22, "section": None, "verified": False},
    "崔呈秀": {"volume": 306, "section": "崔呈秀", "verified": True},
    "田尔耕": {"volume": 306, "section": "田爾耕", "verified": True},
    "许显纯": {"volume": 306, "section": "許顯純", "verified": True},
    "冯铨": {"volume": 22, "section": None, "verified": False},
}


def _specific_source(volume: int, section: str | None) -> dict[str, str]:
    url = f"https://zh.wikisource.org/wiki/%E6%98%8E%E5%8F%B2/%E5%8D%B7{volume}"
    locator = (
        f"卷{volume}·{section}"
        if section
        else f"卷{volume}（API候选，待人工复核）"
    )
    return {
        "title": f"《明史/卷{volume}》",
        "url": url,
        "tier": "A_PRIMARY",
        "locator": locator,
    }


def _merge_sources(existing: list[dict], specific: dict) -> list[dict]:
    # Keep canonical sources while putting specific primary locator first.
    kept = []
    seen = set()
    for src in [specific] + existing:
        key = (src.get("title"), src.get("url"))
        if key in seen:
            continue
        seen.add(key)
        kept.append(src)
    return kept


def main() -> int:
    rows = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    updated = 0
    verified_count = 0
    for row in rows:
        name = row.get("name")
        cfg = MAPPING.get(name)
        if not cfg:
            continue

        specific = _specific_source(cfg["volume"], cfg["section"])
        sources = row.get("sources", [])
        if not isinstance(sources, list):
            sources = []
        row["sources"] = _merge_sources(sources, specific)

        if cfg["verified"]:
            row["review"] = {
                "status": "verified",
                "reviewer": "codex",
                "last_reviewed_on": REVIEW_DATE,
                "notes": (
                    "已通过维基文库API定位到《明史》卷次并命中卷内人物小节。"
                    "生卒年暂未在一手条目中直接核定，先保留null。"
                ),
            }
            verified_count += 1
        else:
            row["review"] = {
                "status": "in_review",
                "reviewer": "codex",
                "last_reviewed_on": REVIEW_DATE,
                "notes": (
                    "已定位《明史》候选卷次，但未命中卷内人物小节，"
                    "需人工复核后再转verified。"
                ),
            }
        updated += 1

    REVIEW_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {updated} entries; verified={verified_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
