"""SQLite persistence for safe AI capability summaries."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .saves import _connect


_SCENARIOS = (
    "structured_schema",
    "state_grounding",
    "causal_adjudication",
    "short_memory",
)
_TIERS = {"excellent", "usable", "high_risk"}
_STATUSES = {"pass", "warn", "fail"}
_REPORT_KEYS = {
    "tier",
    "results",
    "calls_completed",
    "usage",
    "assessed_at",
    "validator_version",
    "stopped_by_transport",
    "provider",
    "provider_type",
    "model",
}


def _safe_text(value: object, *, max_length: int = 256) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_length:
        return None
    return cleaned


def _validated_report(report: object) -> dict[str, Any] | None:
    if not isinstance(report, dict) or set(report) != _REPORT_KEYS:
        return None
    if report.get("tier") not in _TIERS:
        return None
    calls_completed = report.get("calls_completed")
    if (
        not isinstance(calls_completed, int)
        or isinstance(calls_completed, bool)
        or not 0 <= calls_completed <= len(_SCENARIOS)
    ):
        return None
    if not isinstance(report.get("stopped_by_transport"), bool):
        return None

    results = report.get("results")
    if not isinstance(results, list) or len(results) != len(_SCENARIOS):
        return None
    safe_results: list[dict[str, str]] = []
    for expected_scenario, item in zip(_SCENARIOS, results, strict=True):
        if not isinstance(item, dict) or set(item) != {
            "scenario",
            "status",
            "explanation",
        }:
            return None
        if item.get("scenario") != expected_scenario or item.get("status") not in _STATUSES:
            return None
        explanation = _safe_text(item.get("explanation"), max_length=320)
        if explanation is None:
            return None
        safe_results.append(
            {
                "scenario": expected_scenario,
                "status": str(item["status"]),
                "explanation": explanation,
            },
        )

    usage = report.get("usage")
    safe_usage: dict[str, int] | None
    if usage is None:
        safe_usage = None
    elif isinstance(usage, dict) and set(usage) == {"input_tokens", "output_tokens"}:
        values = (usage.get("input_tokens"), usage.get("output_tokens"))
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in values
        ):
            return None
        safe_usage = {
            "input_tokens": int(values[0]),
            "output_tokens": int(values[1]),
        }
    else:
        return None

    assessed_at = _safe_text(report.get("assessed_at"), max_length=64)
    validator_version = _safe_text(report.get("validator_version"), max_length=96)
    provider = _safe_text(report.get("provider"))
    provider_type = _safe_text(report.get("provider_type"))
    model = _safe_text(report.get("model"))
    if None in {assessed_at, validator_version, provider, provider_type, model}:
        return None
    return {
        "tier": report["tier"],
        "results": safe_results,
        "calls_completed": calls_completed,
        "usage": safe_usage,
        "assessed_at": assessed_at,
        "validator_version": validator_version,
        "stopped_by_transport": report["stopped_by_transport"],
        "provider": provider,
        "provider_type": provider_type,
        "model": model,
    }


def init_ai_assessments() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_assessments (
                fingerprint TEXT PRIMARY KEY,
                validator_version TEXT NOT NULL,
                assessed_at TEXT NOT NULL,
                report_json TEXT NOT NULL
            )
            """,
        )


def save_assessment(fingerprint: str, report: dict[str, Any]) -> None:
    safe_report = _validated_report(report)
    if safe_report is None:
        raise ValueError("invalid AI assessment report")
    safe_json = json.dumps(safe_report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO ai_assessments (fingerprint, validator_version, assessed_at, report_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                validator_version = excluded.validator_version,
                assessed_at = excluded.assessed_at,
                report_json = excluded.report_json
            """,
            (
                fingerprint,
                str(safe_report["validator_version"]),
                str(safe_report["assessed_at"]),
                safe_json,
            ),
        )


def load_assessment(fingerprint: str) -> dict[str, Any] | None:
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT report_json FROM ai_assessments WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    try:
        payload = json.loads(row["report_json"])
    except (json.JSONDecodeError, TypeError):
        return None
    return _validated_report(payload)
