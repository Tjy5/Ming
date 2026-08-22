from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from models.game import HistoryEntry


FIXTURE_DIR = Path(__file__).with_name("fixtures")


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_manifest(name: str) -> dict[str, Any]:
    path = FIXTURE_DIR / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = payload.get("manifest_sha256")
    canonical = dict(payload)
    canonical.pop("manifest_sha256", None)
    actual = canonical_sha256(canonical)
    if expected != actual:
        raise AssertionError(f"{name} manifest hash mismatch: {actual}")
    return payload


def deterministic_ascii(seed: int, key: str, length: int) -> str:
    chunks: list[str] = []
    counter = 0
    remaining = max(0, length)
    while remaining:
        digest = hashlib.sha256(f"{seed}:{key}:{counter}".encode("utf-8")).hexdigest()
        chunk = digest[:remaining]
        chunks.append(chunk)
        remaining -= len(chunk)
        counter += 1
    return "".join(chunks)


def storage_payload_rule_sha256(manifest: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    seed = int(manifest["seed"])
    for branch, count in manifest["branch_snapshot_counts"].items():
        for local_index in range(int(count)):
            digest.update(
                hashlib.sha256(
                    f"{seed}:{branch}:{local_index}:{manifest['payload_rule']}".encode(
                        "utf-8",
                    ),
                ).digest(),
            )
    return digest.hexdigest()


def build_history_entries(manifest: dict[str, Any]) -> list[HistoryEntry]:
    seed = int(manifest["seed"])
    start_year = int(manifest["start_year"])
    year_count = int(manifest["year_count"])
    categories = list(manifest["categories"])
    provinces = list(manifest["provinces"])
    entries: list[HistoryEntry] = []
    for sequence in range(int(manifest["entry_count"])):
        digest = hashlib.sha256(f"{seed}:{sequence}".encode("ascii")).digest()
        year = start_year + int.from_bytes(digest[0:2], "big") % year_count
        month = 1 + int.from_bytes(digest[2:4], "big") % 12
        category = categories[int.from_bytes(digest[4:6], "big") % len(categories)]
        province = provinces[int.from_bytes(digest[6:8], "big") % len(provinces)]
        entries.append(
            HistoryEntry(
                sequence=sequence,
                year=year,
                month=month,
                decree_type=category,
                category=category,
                provinces=[province],
                decree_desc=f"history-v1:{sequence}",
                delta={"fixture": sequence % 17},
                narrative=f"固定历史记录 {sequence}",
            ),
        )
    return entries


def history_dataset_sha256(entries: list[HistoryEntry]) -> str:
    return canonical_sha256([entry.model_dump(mode="json") for entry in entries])


def history_result_sha256(entries: list[HistoryEntry]) -> str:
    return canonical_sha256([entry.sequence for entry in entries])


def prompt_case_input_sha256(case: dict[str, Any]) -> str:
    return canonical_sha256(
        {
            "case_id": case["case_id"],
            "target": case["target"],
            "action_text": case["action_text"],
        },
    )


def percentile_ms(samples: list[float], percentile: float) -> float:
    if not samples:
        raise ValueError("samples must not be empty")
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * percentile) - 1))
    return ordered[index] * 1000
