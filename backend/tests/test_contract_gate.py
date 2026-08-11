from __future__ import annotations

from pathlib import Path

import pytest

from quality.contract_gate import (
    CaseResult,
    GateCategory,
    GateManifest,
    RequiredCase,
    evaluate_contract_gate,
    load_manifest,
    run_pytest_contract_gate,
)


MANIFEST = Path(__file__).with_name("contract_matrix.json")


def _passing_results(tmp_path):
    manifest = load_manifest(MANIFEST)
    results = []
    for category in manifest.categories:
        for case in category.cases:
            artifact = f"{case.case_id}.json"
            (tmp_path / artifact).write_text("{}", encoding="utf-8")
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    discovered=True,
                    ran=True,
                    passed=True,
                    artifact=artifact,
                    command=f"pytest -k {case.case_id}",
                ),
            )
    return manifest, results


def test_every_named_required_category_must_be_complete(tmp_path):
    manifest, results = _passing_results(tmp_path)
    report = evaluate_contract_gate(manifest, results, artifact_root=tmp_path)
    assert report.green is True
    assert all(category.green for category in report.categories)


def test_failure_skip_zero_discovery_and_missing_artifact_each_fail(tmp_path):
    manifest, passing = _passing_results(tmp_path)
    mutations = [
        {"passed": False},
        {"skipped": True, "passed": False},
        {"discovered": False, "ran": False, "passed": False},
        {"artifact": "missing.json"},
    ]
    for mutation in mutations:
        changed = list(passing)
        changed[0] = changed[0].model_copy(update=mutation)
        report = evaluate_contract_gate(manifest, changed, artifact_root=tmp_path)
        assert report.green is False
        assert report.categories[0].green is False


def test_pytest_runner_uses_real_discovery_execution_and_junit_artifact(tmp_path):
    (tmp_path / "test_gate_case.py").write_text(
        "def test_gate_case():\n    assert True\n",
        encoding="utf-8",
    )
    manifest = GateManifest(
        categories=[
            GateCategory(
                category="example",
                cases=[
                    RequiredCase(
                        case_id="real_pytest_case",
                        node_id="test_gate_case.py::test_gate_case",
                    ),
                ],
            ),
        ],
    )

    report, results = run_pytest_contract_gate(
        manifest,
        artifact_root=tmp_path / "artifacts",
        cwd=tmp_path,
    )

    assert report.green is True
    assert results[0].discovered is True
    assert results[0].ran is True
    assert results[0].passed is True
    assert (tmp_path / "artifacts" / results[0].artifact).is_file()


def test_duplicate_manifest_or_result_case_ids_cannot_turn_a_failure_green(tmp_path):
    case = RequiredCase(case_id="duplicate", node_id="test_gate_case.py::test_gate_case")
    with pytest.raises(ValueError, match="globally unique"):
        GateManifest(
            categories=[
                GateCategory(category="one", cases=[case]),
                GateCategory(category="two", cases=[case]),
            ],
        )

    manifest = GateManifest(categories=[GateCategory(category="one", cases=[case])])
    duplicate_results = [
        CaseResult(case_id="duplicate", discovered=True, ran=True, passed=False),
        CaseResult(case_id="duplicate", discovered=True, ran=True, passed=True),
    ]
    with pytest.raises(ValueError, match="unique case_id"):
        evaluate_contract_gate(manifest, duplicate_results, artifact_root=tmp_path)
