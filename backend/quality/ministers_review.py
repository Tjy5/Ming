from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ALLOWED_SOURCE_TIERS = {"A_PRIMARY", "B_DATABASE", "C_SECONDARY"}
ALLOWED_REVIEW_STATUS = {"pending", "in_review", "verified", "rejected"}

DEFAULT_MINISTERS_PATH = Path("data/ministers.json")
DEFAULT_REVIEW_PATH = Path("data/ministers_review.json")
DEFAULT_REPORT_PATH = Path("data/ministers_review_report.md")


@dataclass
class AuditIssue:
    level: str
    code: str
    name: str
    message: str


@dataclass
class AuditResult:
    minister_count: int
    review_entry_count: int
    issues: list[AuditIssue] = field(default_factory=list)

    def add(self, level: str, code: str, name: str, message: str) -> None:
        self.issues.append(AuditIssue(level=level, code=code, name=name, message=message))

    @property
    def errors(self) -> list[AuditIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[AuditIssue]:
        return [i for i in self.issues if i.level == "warning"]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_ministers(path: Path) -> list[dict[str, Any]]:
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise ValueError(f"Expected a list in {path}")
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Minister entry #{idx + 1} is not an object")
        if not _is_non_empty_string(item.get("name")):
            raise ValueError(f"Minister entry #{idx + 1} has invalid name")
    return raw


def load_review_entries(path: Path) -> list[dict[str, Any]]:
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise ValueError(f"Expected a list in {path}")
    return raw


def scaffold_review_entries(ministers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for minister in ministers:
        entries.append(
            {
                "name": minister["name"],
                "base_profile": {
                    "faction": minister.get("faction", ""),
                    "position": minister.get("position", ""),
                    "historical_note": minister.get("historical_note", ""),
                },
                "aliases": [],
                "birth_year": None,
                "death_year": None,
                "office_history": [],
                "major_contributions": [],
                "related_events": [],
                "project_role_background": "",
                "sources": [],
                "review": {
                    "status": "pending",
                    "reviewer": "",
                    "last_reviewed_on": "",
                    "notes": "",
                },
            }
        )
    return entries


def _validate_year_field(
    result: AuditResult, name: str, field_name: str, value: Any
) -> None:
    if value is None:
        return
    if not isinstance(value, int):
        result.add(
            "error",
            "invalid_year_type",
            name,
            f"{field_name} must be an integer or null",
        )


def _validate_string_list(
    result: AuditResult, name: str, field_name: str, value: Any
) -> None:
    if not isinstance(value, list):
        result.add("error", "invalid_list_type", name, f"{field_name} must be a list")
        return
    for idx, item in enumerate(value):
        if not _is_non_empty_string(item):
            result.add(
                "error",
                "invalid_list_item",
                name,
                f"{field_name}[{idx}] must be a non-empty string",
            )


def _validate_source_items(result: AuditResult, name: str, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        result.add("error", "invalid_sources_type", name, "sources must be a list")
        return []

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            result.add("error", "invalid_source_item", name, f"sources[{idx}] must be an object")
            continue
        title = item.get("title")
        url = item.get("url")
        tier = item.get("tier")
        locator = item.get("locator", "")
        if not _is_non_empty_string(title):
            result.add("error", "invalid_source_title", name, f"sources[{idx}].title is required")
        if not _is_non_empty_string(url):
            result.add("error", "invalid_source_url", name, f"sources[{idx}].url is required")
        if tier not in ALLOWED_SOURCE_TIERS:
            result.add(
                "error",
                "invalid_source_tier",
                name,
                f"sources[{idx}].tier must be one of {sorted(ALLOWED_SOURCE_TIERS)}",
            )
        if locator is not None and not isinstance(locator, str):
            result.add("error", "invalid_source_locator", name, f"sources[{idx}].locator must be a string")
        normalized.append(item)
    return normalized


def _validate_review_block(result: AuditResult, name: str, value: Any) -> str:
    if not isinstance(value, dict):
        result.add("error", "invalid_review_block", name, "review must be an object")
        return "pending"
    status = value.get("status")
    if status not in ALLOWED_REVIEW_STATUS:
        result.add(
            "error",
            "invalid_review_status",
            name,
            f"review.status must be one of {sorted(ALLOWED_REVIEW_STATUS)}",
        )
        return "pending"
    for key in ("reviewer", "last_reviewed_on", "notes"):
        val = value.get(key, "")
        if val is not None and not isinstance(val, str):
            result.add("error", "invalid_review_field", name, f"review.{key} must be a string")
    return status


def validate_review_entries(
    ministers: list[dict[str, Any]],
    review_entries: list[dict[str, Any]],
    *,
    strict: bool = False,
) -> AuditResult:
    minister_names = [m["name"] for m in ministers]
    minister_name_set = set(minister_names)
    result = AuditResult(minister_count=len(ministers), review_entry_count=len(review_entries))

    seen_entry_names: set[str] = set()
    for idx, entry in enumerate(review_entries):
        if not isinstance(entry, dict):
            result.add("error", "invalid_entry_type", f"#{idx + 1}", "review entry must be an object")
            continue
        name = entry.get("name")
        if not _is_non_empty_string(name):
            result.add("error", "invalid_entry_name", f"#{idx + 1}", "name is required")
            continue
        if name in seen_entry_names:
            result.add("error", "duplicate_review_entry", name, "duplicate review entry name")
        seen_entry_names.add(name)
        if name not in minister_name_set:
            result.add("warning", "unknown_review_entry", name, "name not found in ministers.json")

        _validate_string_list(result, name, "aliases", entry.get("aliases", []))
        _validate_string_list(
            result, name, "major_contributions", entry.get("major_contributions", [])
        )
        _validate_string_list(result, name, "related_events", entry.get("related_events", []))

        _validate_year_field(result, name, "birth_year", entry.get("birth_year"))
        _validate_year_field(result, name, "death_year", entry.get("death_year"))
        birth_year = entry.get("birth_year")
        death_year = entry.get("death_year")
        if isinstance(birth_year, int) and isinstance(death_year, int) and birth_year > death_year:
            result.add("error", "invalid_lifespan", name, "birth_year must not be greater than death_year")

        sources = _validate_source_items(result, name, entry.get("sources", []))
        _validate_review_block(result, name, entry.get("review", {}))

        project_role_background = entry.get("project_role_background", "")
        if project_role_background is not None and not isinstance(project_role_background, str):
            result.add(
                "error",
                "invalid_project_role_background",
                name,
                "project_role_background must be a string",
            )

        if strict:
            contributions = entry.get("major_contributions", [])
            events = entry.get("related_events", [])
            if not _is_non_empty_string(project_role_background):
                result.add(
                    "error",
                    "strict_project_role_missing",
                    name,
                    "project_role_background is required in strict mode",
                )
            if not isinstance(contributions, list) or len(contributions) < 1:
                result.add(
                    "error",
                    "strict_contributions_missing",
                    name,
                    "major_contributions requires at least 1 item in strict mode",
                )
            if not isinstance(events, list) or len(events) < 1:
                result.add(
                    "error",
                    "strict_events_missing",
                    name,
                    "related_events requires at least 1 item in strict mode",
                )
            if len(sources) < 2:
                result.add(
                    "error",
                    "strict_min_sources",
                    name,
                    "at least 2 sources are required in strict mode",
                )
            has_primary_source = any(src.get("tier") == "A_PRIMARY" for src in sources if isinstance(src, dict))
            if not has_primary_source:
                result.add(
                    "error",
                    "strict_primary_source_missing",
                    name,
                    "at least 1 A_PRIMARY source is required in strict mode",
                )

    missing_names = [name for name in minister_names if name not in seen_entry_names]
    for name in missing_names:
        result.add("error", "missing_review_entry", name, "missing review entry for minister")

    return result


def build_markdown_report(result: AuditResult, *, strict: bool, review_path: Path) -> str:
    lines: list[str] = []
    lines.append("# 明朝大臣史实审查报告")
    lines.append("")
    lines.append(f"- 审查模式：`{'strict' if strict else 'normal'}`")
    lines.append(f"- 审查文件：`{review_path}`")
    lines.append(f"- 大臣总数：`{result.minister_count}`")
    lines.append(f"- 审校条目数：`{result.review_entry_count}`")
    lines.append(f"- 错误：`{len(result.errors)}`")
    lines.append(f"- 警告：`{len(result.warnings)}`")
    lines.append("")

    if not result.issues:
        lines.append("## 结果")
        lines.append("")
        lines.append("未发现问题。")
        lines.append("")
        return "\n".join(lines)

    lines.append("## 问题清单")
    lines.append("")
    lines.append("| Level | Code | Name | Message |")
    lines.append("| --- | --- | --- | --- |")
    for issue in result.issues:
        lines.append(
            f"| {issue.level} | {issue.code} | {issue.name} | {issue.message} |"
        )
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_init(ministers_path: Path, output_path: Path, force: bool) -> int:
    if output_path.exists() and not force:
        print(f"Refusing to overwrite existing file: {output_path} (use --force to overwrite)")
        return 2
    ministers = load_ministers(ministers_path)
    entries = scaffold_review_entries(ministers)
    _write_json(output_path, entries)
    print(f"Initialized review file: {output_path} ({len(entries)} entries)")
    return 0


def run_audit(
    ministers_path: Path,
    review_path: Path,
    report_path: Path,
    strict: bool,
) -> int:
    ministers = load_ministers(ministers_path)
    review_entries = load_review_entries(review_path)
    result = validate_review_entries(ministers, review_entries, strict=strict)
    report = build_markdown_report(result, strict=strict, review_path=review_path)
    report_path.write_text(report, encoding="utf-8")
    print(
        f"Audit completed: errors={len(result.errors)}, warnings={len(result.warnings)}, "
        f"report={report_path}"
    )
    return 1 if result.errors else 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minister historical review workflow tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a review file from ministers.json")
    init_parser.add_argument("--ministers", type=Path, default=DEFAULT_MINISTERS_PATH)
    init_parser.add_argument("--output", type=Path, default=DEFAULT_REVIEW_PATH)
    init_parser.add_argument("--force", action="store_true")

    audit_parser = subparsers.add_parser("audit", help="Audit review file quality")
    audit_parser.add_argument("--ministers", type=Path, default=DEFAULT_MINISTERS_PATH)
    audit_parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW_PATH)
    audit_parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    audit_parser.add_argument("--strict", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        return run_init(args.ministers, args.output, args.force)
    if args.command == "audit":
        return run_audit(args.ministers, args.review, args.report, args.strict)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
