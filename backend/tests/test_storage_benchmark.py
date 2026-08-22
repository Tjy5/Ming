from __future__ import annotations

import statistics

from db import maintenance, saves, worlds
from tests.benchmarks.manifests import load_manifest
from tests.benchmarks.storage_fixture import generate_storage_fixture


def test_storage_v1_retention_and_vacuum_gate(monkeypatch, tmp_path):
    manifest = load_manifest("storage-v1.json")
    db_path = tmp_path / "storage-v1.db"
    monkeypatch.setattr(saves, "DB_PATH", db_path)
    monkeypatch.setenv(
        "STORAGE_RETENTION_RECENT_LIMIT",
        str(manifest["recent_limit"]),
    )
    fixture = generate_storage_fixture(db_path, manifest)

    assert sum(len(refs) for refs in fixture.branches.values()) == manifest["snapshot_count"]
    average_size = statistics.mean(fixture.serialized_sizes)
    tolerance = manifest["snapshot_size_tolerance_percent"] / 100
    assert abs(average_size - manifest["target_snapshot_bytes"]) <= (
        manifest["target_snapshot_bytes"] * tolerance
    )
    for branch, refs in fixture.branches.items():
        assert len(refs) == manifest["branch_snapshot_counts"][branch]

    result = maintenance.run_storage_maintenance("manual")

    assert result.status == "success"
    assert result.size_before > 0
    assert result.size_after / result.size_before <= manifest["max_post_vacuum_ratio"]
    protected = [
        *(refs[0].version_id for refs in fixture.branches.values()),
        *(refs[-1].version_id for refs in fixture.branches.values()),
        *fixture.bookmark_version_ids,
    ]
    for version_id in protected:
        assert worlds.load_version(version_id).state.world_metadata.version_id == version_id
