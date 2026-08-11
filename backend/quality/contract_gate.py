"""Named deterministic contract gate; aggregate percentages are intentionally absent."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _GateContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RequiredCase(_GateContract):
    case_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    artifact_required: bool = True


class GateCategory(_GateContract):
    category: str = Field(min_length=1)
    cases: list[RequiredCase] = Field(min_length=1)


class GateManifest(_GateContract):
    schema_version: int = 1
    categories: list[GateCategory] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_unique_names(self) -> "GateManifest":
        category_names = [category.category for category in self.categories]
        case_ids = [
            case.case_id
            for category in self.categories
            for case in category.cases
        ]
        if len(category_names) != len(set(category_names)):
            raise ValueError("gate category names must be unique")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("gate case_id values must be globally unique")
        return self


class CaseResult(_GateContract):
    case_id: str
    discovered: bool
    ran: bool
    passed: bool
    skipped: bool = False
    artifact: str | None = None
    command: str = ""
    duration_ms: int = Field(default=0, ge=0)


class CategoryReport(_GateContract):
    category: str
    required: int
    discovered: int
    ran: int
    passed: int
    failed: int
    skipped: int
    missing_artifacts: list[str] = Field(default_factory=list)
    green: bool


class GateReport(_GateContract):
    schema_version: int = 1
    categories: list[CategoryReport]
    green: bool


def load_manifest(path: Path) -> GateManifest:
    return GateManifest.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate_contract_gate(
    manifest: GateManifest,
    results: list[CaseResult],
    *,
    artifact_root: Path,
) -> GateReport:
    result_ids = [result.case_id for result in results]
    if len(result_ids) != len(set(result_ids)):
        raise ValueError("gate case results must have unique case_id values")
    by_id = {result.case_id: result for result in results}
    reports: list[CategoryReport] = []
    for category in manifest.categories:
        category_results = [by_id.get(case.case_id) for case in category.cases]
        missing_artifacts: list[str] = []
        for case, result in zip(category.cases, category_results):
            if not case.artifact_required:
                continue
            if (
                result is None
                or result.artifact is None
                or not (artifact_root / result.artifact).is_file()
            ):
                missing_artifacts.append(case.case_id)
        discovered = sum(result is not None and result.discovered for result in category_results)
        ran = sum(result is not None and result.ran for result in category_results)
        passed = sum(result is not None and result.passed for result in category_results)
        skipped = sum(result is not None and result.skipped for result in category_results)
        required = len(category.cases)
        failed = required - passed
        green = (
            discovered == required
            and ran == required
            and passed == required
            and skipped == 0
            and not missing_artifacts
        )
        reports.append(
            CategoryReport(
                category=category.category,
                required=required,
                discovered=discovered,
                ran=ran,
                passed=passed,
                failed=failed,
                skipped=skipped,
                missing_artifacts=missing_artifacts,
                green=green,
            ),
        )
    return GateReport(categories=reports, green=all(report.green for report in reports))


def write_report(report: GateReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _junit_counts(path: Path) -> tuple[int, int, int, int]:
    root = ElementTree.parse(path).getroot()
    if root.tag == "testsuite":
        suites = [root]
    else:
        suites = list(root.findall("testsuite"))
    return (
        sum(int(suite.attrib.get("tests", 0)) for suite in suites),
        sum(int(suite.attrib.get("failures", 0)) for suite in suites),
        sum(int(suite.attrib.get("errors", 0)) for suite in suites),
        sum(int(suite.attrib.get("skipped", 0)) for suite in suites),
    )


def run_pytest_contract_gate(
    manifest: GateManifest,
    *,
    artifact_root: Path,
    cwd: Path,
) -> tuple[GateReport, list[CaseResult]]:
    """Run each named pytest node and emit one JUnit artifact per required case."""

    artifact_root.mkdir(parents=True, exist_ok=True)
    case_root = artifact_root / "cases"
    case_root.mkdir(parents=True, exist_ok=True)
    results: list[CaseResult] = []
    for category in manifest.categories:
        for case in category.cases:
            junit_path = case_root / f"{case.case_id}.xml"
            command = [
                sys.executable,
                "-m",
                "pytest",
                case.node_id,
                "-q",
                "-rs",
                f"--junitxml={junit_path}",
            ]
            started = time.perf_counter()
            completed = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            tests = failures = errors = skipped = 0
            if junit_path.is_file():
                try:
                    tests, failures, errors, skipped = _junit_counts(junit_path)
                except (ElementTree.ParseError, OSError, ValueError):
                    pass
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    discovered=tests > 0,
                    ran=tests - skipped > 0,
                    passed=(
                        completed.returncode == 0
                        and tests > 0
                        and failures == 0
                        and errors == 0
                        and skipped == 0
                    ),
                    skipped=skipped > 0,
                    artifact=(
                        str(junit_path.relative_to(artifact_root)).replace("\\", "/")
                        if junit_path.is_file()
                        else None
                    ),
                    command=shlex.join(command),
                    duration_ms=duration_ms,
                ),
            )
    report = evaluate_contract_gate(manifest, results, artifact_root=artifact_root)
    write_report(report, artifact_root / "contract-gate-report.json")
    return report, results
