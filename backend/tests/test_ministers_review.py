from pathlib import Path

from quality.ministers_review import (
    build_markdown_report,
    scaffold_review_entries,
    validate_review_entries,
)


def _sample_ministers() -> list[dict]:
    return [
        {
            "name": "韩爌",
            "faction": "东林党",
            "position": "礼部尚书兼东阁大学士",
            "historical_note": "崇祯即位后起复入阁。",
        },
        {
            "name": "温体仁",
            "faction": "温体仁派",
            "position": "礼部侍郎",
            "historical_note": "后为首辅。",
        },
    ]


def test_scaffold_entries_from_ministers():
    entries = scaffold_review_entries(_sample_ministers())
    assert len(entries) == 2
    assert entries[0]["name"] == "韩爌"
    assert entries[0]["base_profile"]["position"] == "礼部尚书兼东阁大学士"
    assert entries[0]["review"]["status"] == "pending"


def test_validate_detects_missing_and_unknown_entries():
    ministers = _sample_ministers()
    entries = scaffold_review_entries([ministers[0]])
    entries.append(
        {
            "name": "不存在人物",
            "base_profile": {"faction": "", "position": "", "historical_note": ""},
            "aliases": [],
            "birth_year": None,
            "death_year": None,
            "office_history": [],
            "major_contributions": [],
            "related_events": [],
            "project_role_background": "",
            "sources": [],
            "review": {"status": "pending", "reviewer": "", "last_reviewed_on": "", "notes": ""},
        }
    )
    result = validate_review_entries(ministers, entries, strict=False)

    error_codes = {issue.code for issue in result.errors}
    warning_codes = {issue.code for issue in result.warnings}
    assert "missing_review_entry" in error_codes
    assert "unknown_review_entry" in warning_codes


def test_validate_strict_requires_sources_and_fields():
    ministers = [_sample_ministers()[0]]
    entry = scaffold_review_entries(ministers)[0]
    result = validate_review_entries(ministers, [entry], strict=True)
    error_codes = {issue.code for issue in result.errors}
    assert "strict_project_role_missing" in error_codes
    assert "strict_contributions_missing" in error_codes
    assert "strict_events_missing" in error_codes
    assert "strict_min_sources" in error_codes
    assert "strict_primary_source_missing" in error_codes


def test_validate_strict_passes_with_complete_entry():
    ministers = [_sample_ministers()[0]]
    entry = scaffold_review_entries(ministers)[0]
    entry["birth_year"] = 1563
    entry["death_year"] = 1638
    entry["major_contributions"] = ["参与倒魏善后，主持朝政重整。"]
    entry["related_events"] = ["崇祯初年东林复起。"]
    entry["project_role_background"] = "早期中枢重臣，可影响东林党与朝廷稳定。"
    entry["sources"] = [
        {
            "title": "《明史/卷72》",
            "url": "https://zh.wikisource.org/wiki/%E6%98%8E%E5%8F%B2/%E5%8D%B772",
            "tier": "A_PRIMARY",
            "locator": "卷72",
        },
        {
            "title": "CBDB",
            "url": "https://cbdb.hsites.harvard.edu/",
            "tier": "B_DATABASE",
            "locator": "",
        },
    ]
    entry["review"]["status"] = "verified"

    result = validate_review_entries(ministers, [entry], strict=True)
    assert result.errors == []
    report = build_markdown_report(result, strict=True, review_path=Path("backend/data/ministers_review.json"))
    assert "错误：`0`" in report
