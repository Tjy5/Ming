from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from db import saves, worlds
from engine.calendar import set_game_time_projection
from models.game import GameState, HistoryEntry
from models.settlement import ActionIntent, AdjudicationProposal
from models.world import GameId, VersionId, WorldVersionRef, new_client_action_id
from tests.benchmarks.manifests import deterministic_ascii


@dataclass(frozen=True)
class StorageFixtureResult:
    game_id: GameId
    branches: dict[str, tuple[WorldVersionRef, ...]]
    bookmark_version_ids: tuple[VersionId, ...]
    serialized_sizes: tuple[int, ...]


def _serialized_size(state) -> int:
    return len(state.model_dump_json().encode("utf-8"))


def _fit_snapshot_payload(
    state,
    *,
    seed: int,
    branch: str,
    local_index: int,
    target_bytes: int,
) -> None:
    month_index = local_index % 24
    set_game_time_projection(
        state.time,
        year=1350 + month_index // 12,
        month=month_index % 12 + 1,
        migration_source="legacy_year_month",
    )
    entry = HistoryEntry(
        sequence=0,
        year=state.time.year,
        month=state.time.month,
        decree_type="other",
        category="other",
        provinces=[],
        decree_desc=f"storage-v1:{branch}:{local_index}",
        delta={"branch": branch, "local_index": local_index},
        narrative="",
    )
    state.history_log = [entry]
    key = f"{branch}:{local_index}"
    padding_length = target_bytes - _serialized_size(state)
    if padding_length < 0:
        raise AssertionError("canonical GameState exceeds storage-v1 snapshot target")
    for _ in range(3):
        entry.narrative = deterministic_ascii(seed, key, padding_length)
        difference = target_bytes - _serialized_size(state)
        if difference == 0:
            break
        padding_length += difference
        if padding_length < 0:
            raise AssertionError("storage-v1 padding calculation underflowed")
    if _serialized_size(state) != target_bytes:
        raise AssertionError("storage-v1 snapshot could not be sized deterministically")


def generate_storage_fixture(
    db_path: Path,
    manifest: dict,
) -> StorageFixtureResult:
    saves.DB_PATH = db_path
    saves.init_db()
    seed = int(manifest["seed"])
    target_bytes = int(manifest["target_snapshot_bytes"])

    root = worlds.create_game_with_root(GameState())
    fork_b = worlds.create_branch_from_version(root.version_id)
    fork_c = worlds.create_branch_from_version(root.version_id)
    branches: dict[str, list[WorldVersionRef]] = {
        "A": [root],
        "B": [fork_b],
        "C": [fork_c],
    }
    sizes = [
        _serialized_size(worlds.load_version(root.version_id).state),
        _serialized_size(worlds.load_version(fork_b.version_id).state),
        _serialized_size(worlds.load_version(fork_c.version_id).state),
    ]

    for branch, snapshot_count in manifest["branch_snapshot_counts"].items():
        parent = branches[branch][0]
        state = worlds.load_version(parent.version_id).state
        for local_index in range(1, int(snapshot_count)):
            changed = state.model_copy(deep=True)
            _fit_snapshot_payload(
                changed,
                seed=seed,
                branch=branch,
                local_index=local_index,
                target_bytes=target_bytes,
            )
            intent = ActionIntent(
                game_id=parent.game_id,
                branch_id=parent.branch_id,
                expected_parent_version_id=parent.version_id,
                client_action_id=new_client_action_id(),
                raw_text=f"storage-v1:{branch}:{local_index}",
                action_kind="benchmark",
            )
            proposal = AdjudicationProposal(
                result_tier="success",
                key_factors=["storage-v1 deterministic fixture"],
                immediate_changes=["snapshot payload refreshed"],
                execution_status="completed",
            )
            committed = worlds.commit_settlement(intent, changed, proposal)
            parent = committed.version
            state = worlds.load_version(parent.version_id).state
            branches[branch].append(parent)
            sizes.append(_serialized_size(state))

    bookmark_version_ids: list[VersionId] = []
    for branch, indexes in manifest["bookmark_local_indexes"].items():
        for local_index in indexes:
            version = branches[branch][int(local_index)]
            worlds.create_bookmark(
                version.game_id,
                version.branch_id,
                version.version_id,
                f"storage-v1:{branch}:{local_index}",
            )
            bookmark_version_ids.append(version.version_id)

    return StorageFixtureResult(
        game_id=root.game_id,
        branches={key: tuple(value) for key, value in branches.items()},
        bookmark_version_ids=tuple(bookmark_version_ids),
        serialized_sizes=tuple(sizes),
    )
