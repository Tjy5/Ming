from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import ValidationError

from models.game import GameState
from models.settlement import (
    ActionIntent,
    ActionRequestRecord,
    AdjudicationProposal,
    SettlementAttribution,
    SettlementCommitResult,
    SettlementFacts,
)
from models.world import (
    BranchId,
    ClientActionId,
    EntityId,
    EntitySource,
    FactionEntity,
    GameId,
    PersonEntity,
    RegionEntity,
    SettlementId,
    VersionId,
    WorldSnapshotMetadata,
    WorldEntity,
    WorldVersionRef,
    new_branch_id,
    new_entity_id,
    new_game_id,
    new_settlement_id,
    new_version_id,
)


_INITIAL_ENTITY_SOURCE_REF = "yuanming-initial-v1"


@dataclass(frozen=True)
class WorldVersionSnapshot:
    ref: WorldVersionRef
    state: GameState


@dataclass(frozen=True)
class LegacyWorldImportResult:
    version: WorldVersionRef
    state: GameState
    migration_notes: tuple[str, ...]
    source_state_hash: str
    replayed: bool = False

    @property
    def migration_applied(self) -> bool:
        return bool(self.migration_notes)


def _connect() -> sqlite3.Connection:
    # Import lazily: saves.init_db() initializes this additive schema and is the
    # existing owner of the configured SQLite path used by tests and startup.
    from . import saves

    return saves._connect()


def init_worlds_db() -> None:
    """Create the additive immutable-world graph schema.

    Legacy ``saves`` rows remain untouched. All gameplay writes to these tables
    are owned by this module and use explicit transactions below.
    """

    with closing(_connect()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_ref TEXT
            );

            CREATE TABLE IF NOT EXISTS branches (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                parent_branch_id TEXT,
                forked_from_version_id TEXT,
                head_version_id TEXT,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                UNIQUE (game_id, id),
                FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, parent_branch_id)
                    REFERENCES branches(game_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, forked_from_version_id)
                    REFERENCES versions(game_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, id, head_version_id)
                    REFERENCES versions(game_id, branch_id, id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS settlements (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                client_action_id TEXT NOT NULL,
                parent_version_id TEXT NOT NULL,
                facts_json TEXT NOT NULL,
                delta_json TEXT NOT NULL,
                attribution_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (game_id, branch_id, client_action_id),
                UNIQUE (game_id, branch_id, id),
                FOREIGN KEY (game_id, branch_id)
                    REFERENCES branches(game_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, parent_version_id)
                    REFERENCES versions(game_id, branch_id, id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS versions (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                parent_version_id TEXT,
                settlement_id TEXT UNIQUE,
                state_json TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                calendar_schema_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                protected INTEGER NOT NULL DEFAULT 0 CHECK (protected IN (0, 1)),
                source_kind TEXT NOT NULL,
                UNIQUE (game_id, id),
                UNIQUE (game_id, branch_id, id),
                FOREIGN KEY (game_id, branch_id)
                    REFERENCES branches(game_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, parent_version_id)
                    REFERENCES versions(game_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, settlement_id)
                    REFERENCES settlements(game_id, branch_id, id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS action_requests (
                game_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                client_action_id TEXT NOT NULL,
                expected_parent_version_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending', 'completed')),
                settlement_id TEXT,
                version_id TEXT,
                result_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (game_id, branch_id, client_action_id),
                FOREIGN KEY (game_id, branch_id)
                    REFERENCES branches(game_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, expected_parent_version_id)
                    REFERENCES versions(game_id, branch_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, settlement_id)
                    REFERENCES settlements(game_id, branch_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, version_id)
                    REFERENCES versions(game_id, branch_id, id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS bookmarks (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                version_id TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (game_id, branch_id)
                    REFERENCES branches(game_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, version_id)
                    REFERENCES versions(game_id, branch_id, id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS terminal_records (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL UNIQUE,
                version_id TEXT NOT NULL UNIQUE,
                previous_version_id TEXT NOT NULL,
                facts_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (game_id, branch_id)
                    REFERENCES branches(game_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, settlement_id)
                    REFERENCES settlements(game_id, branch_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, version_id)
                    REFERENCES versions(game_id, branch_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, previous_version_id)
                    REFERENCES versions(game_id, branch_id, id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS legacy_save_imports (
                save_id INTEGER PRIMARY KEY,
                game_id TEXT NOT NULL UNIQUE,
                branch_id TEXT NOT NULL UNIQUE,
                version_id TEXT NOT NULL UNIQUE,
                source_name TEXT NOT NULL,
                source_game_time TEXT NOT NULL,
                source_created_at TEXT NOT NULL,
                source_state_bytes BLOB NOT NULL,
                source_state_hash TEXT NOT NULL,
                migration_metadata_json TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                FOREIGN KEY (save_id) REFERENCES saves(id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id)
                    REFERENCES branches(game_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, version_id)
                    REFERENCES versions(game_id, branch_id, id) ON DELETE RESTRICT
            );

            CREATE INDEX IF NOT EXISTS idx_versions_branch_created
                ON versions(game_id, branch_id, created_at, id);
            CREATE INDEX IF NOT EXISTS idx_settlements_branch_created
                ON settlements(game_id, branch_id, created_at, id);
            CREATE INDEX IF NOT EXISTS idx_action_requests_status
                ON action_requests(game_id, branch_id, status);
            """,
        )
        conn.commit()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _begin(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")


def _snapshot_for_version(
    state: GameState,
    *,
    game_id: GameId,
    branch_id: BranchId,
    version_id: VersionId,
    source_kind: str,
    source_ref: str | None,
    imported_at: datetime | None = None,
    migration_notes: list[str] | None = None,
) -> GameState:
    snapshot = state.model_copy(deep=True)
    previous = snapshot.world_metadata
    snapshot.world_metadata = WorldSnapshotMetadata(
        calendar_schema_version=previous.calendar_schema_version,
        game_id=game_id,
        branch_id=branch_id,
        version_id=version_id,
        source_kind=source_kind,
        source_ref=source_ref,
        imported_at=imported_at if imported_at is not None else previous.imported_at,
        migration_notes=(
            list(migration_notes)
            if migration_notes is not None
            else list(previous.migration_notes)
        ),
    )
    return snapshot


def _insert_game(
    conn: sqlite3.Connection,
    game_id: GameId,
    created_at: datetime,
    source_kind: str,
    source_ref: str | None,
) -> None:
    conn.execute(
        "INSERT INTO games (id, created_at, source_kind, source_ref) VALUES (?, ?, ?, ?)",
        (str(game_id), created_at.isoformat(), source_kind, source_ref),
    )


def _insert_branch(
    conn: sqlite3.Connection,
    game_id: GameId,
    branch_id: BranchId,
    created_at: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO branches (
            id, game_id, parent_branch_id, forked_from_version_id,
            head_version_id, created_at, status
        ) VALUES (?, ?, NULL, NULL, NULL, ?, 'active')
        """,
        (str(branch_id), str(game_id), created_at.isoformat()),
    )


def _insert_version(
    conn: sqlite3.Connection,
    *,
    ref: WorldVersionRef,
    state: GameState,
    source_kind: str,
) -> None:
    conn.execute(
        """
        INSERT INTO versions (
            id, game_id, branch_id, parent_version_id, settlement_id,
            state_json, schema_version, calendar_schema_version,
            created_at, protected, source_kind
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(ref.version_id),
            str(ref.game_id),
            str(ref.branch_id),
            str(ref.parent_version_id) if ref.parent_version_id else None,
            str(ref.settlement_id) if ref.settlement_id else None,
            state.model_dump_json(),
            state.world_metadata.schema_version,
            state.world_metadata.calendar_schema_version,
            ref.created_at.isoformat(),
            int(ref.protected),
            source_kind,
        ),
    )


def _advance_branch_head(
    conn: sqlite3.Connection,
    *,
    game_id: GameId,
    branch_id: BranchId,
    expected_version_id: VersionId | None,
    next_version_id: VersionId,
) -> bool:
    if expected_version_id is None:
        cursor = conn.execute(
            """
            UPDATE branches SET head_version_id = ?
            WHERE game_id = ? AND id = ? AND head_version_id IS NULL
            """,
            (str(next_version_id), str(game_id), str(branch_id)),
        )
    else:
        cursor = conn.execute(
            """
            UPDATE branches SET head_version_id = ?
            WHERE game_id = ? AND id = ? AND head_version_id = ?
            """,
            (
                str(next_version_id),
                str(game_id),
                str(branch_id),
                str(expected_version_id),
            ),
        )
    return cursor.rowcount == 1


def _create_root_in_transaction(
    conn: sqlite3.Connection,
    state: GameState,
    *,
    game_id: GameId,
    branch_id: BranchId,
    version_id: VersionId,
    created_at: datetime,
    protected: bool,
    source_kind: str,
    source_ref: str | None,
    imported_at: datetime | None = None,
    migration_notes: list[str] | None = None,
) -> tuple[WorldVersionRef, GameState]:
    _insert_game(conn, game_id, created_at, source_kind, source_ref)
    _insert_branch(conn, game_id, branch_id, created_at)
    snapshot = _snapshot_for_version(
        state,
        game_id=game_id,
        branch_id=branch_id,
        version_id=version_id,
        source_kind=source_kind,
        source_ref=source_ref,
        imported_at=imported_at,
        migration_notes=migration_notes,
    )
    ref = WorldVersionRef(
        game_id=game_id,
        branch_id=branch_id,
        version_id=version_id,
        created_at=created_at,
        protected=protected,
    )
    _insert_version(conn, ref=ref, state=snapshot, source_kind=source_kind)
    if not _advance_branch_head(
        conn,
        game_id=game_id,
        branch_id=branch_id,
        expected_version_id=None,
        next_version_id=version_id,
    ):
        raise WorldCorruptDataError("new branch rejected its root version")
    return ref, snapshot


def create_game_with_root(
    state: GameState,
    *,
    protected: bool = False,
    source_kind: str = "initial",
    source_ref: str | None = None,
) -> WorldVersionRef:
    game_id = new_game_id()
    branch_id = new_branch_id()
    version_id = new_version_id()
    created_at = _utc_now()
    root_state = state.model_copy(deep=True)
    if source_kind == "legacy_save":
        entity_source = EntitySource(
            kind="legacy_save",
            reference=source_ref,
            summary="Projected from an immutable legacy save snapshot",
        )
        player_identity_summary = "Imported player character"
    elif source_kind == "initial":
        entity_source = EntitySource(
            kind="initial_data",
            reference=source_ref or _INITIAL_ENTITY_SOURCE_REF,
            summary="Projected from the Yuan-Ming initial world data",
        )
        player_identity_summary = "Initial player character"
    else:
        entity_source = EntitySource(
            kind="system",
            reference=source_ref,
            summary="Projected while creating a system world root",
        )
        player_identity_summary = "System player character"
    _bootstrap_entity_registry(
        root_state,
        version_id=version_id,
        source=entity_source,
        player_identity_summary=player_identity_summary,
    )

    with closing(_connect()) as conn:
        try:
            _begin(conn)
            ref, _ = _create_root_in_transaction(
                conn,
                root_state,
                game_id=game_id,
                branch_id=branch_id,
                version_id=version_id,
                created_at=created_at,
                protected=protected,
                source_kind=source_kind,
                source_ref=source_ref,
            )
            conn.commit()
            return ref
        except WorldStoreError:
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise WorldStorageError() from exc
        except Exception:
            conn.rollback()
            raise


def _row_to_version_ref(row: sqlite3.Row) -> WorldVersionRef:
    return WorldVersionRef.model_validate(
        {
            "game_id": row["game_id"],
            "branch_id": row["branch_id"],
            "version_id": row["id"],
            "parent_version_id": row["parent_version_id"],
            "settlement_id": row["settlement_id"],
            "created_at": row["created_at"],
            "protected": bool(row["protected"]),
        },
    )


def _load_version(
    conn: sqlite3.Connection,
    version_id: VersionId | str,
) -> WorldVersionSnapshot:
    row = conn.execute(
        """
        SELECT id, game_id, branch_id, parent_version_id, settlement_id,
               state_json, created_at, protected
        FROM versions WHERE id = ?
        """,
        (str(version_id),),
    ).fetchone()
    if row is None:
        raise WorldNotFoundError("version", str(version_id))
    try:
        return WorldVersionSnapshot(
            ref=_row_to_version_ref(row),
            state=GameState.model_validate_json(row["state_json"]),
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise WorldCorruptDataError("stored world version is invalid") from exc


def load_version(version_id: VersionId) -> WorldVersionSnapshot:
    try:
        with closing(_connect()) as conn:
            return _load_version(conn, version_id)
    except WorldStoreError:
        raise
    except sqlite3.Error as exc:
        raise WorldStorageError() from exc


def _get_branch_head(
    conn: sqlite3.Connection,
    game_id: GameId | str,
    branch_id: BranchId | str,
) -> WorldVersionRef:
    row = conn.execute(
        """
        SELECT v.id, v.game_id, v.branch_id, v.parent_version_id,
               v.settlement_id, v.created_at, v.protected
        FROM branches AS b
        JOIN versions AS v ON v.id = b.head_version_id
        WHERE b.game_id = ? AND b.id = ?
        """,
        (str(game_id), str(branch_id)),
    ).fetchone()
    if row is None:
        raise WorldNotFoundError("branch", str(branch_id))
    return _row_to_version_ref(row)


def get_branch_head(game_id: GameId, branch_id: BranchId) -> WorldVersionRef:
    try:
        with closing(_connect()) as conn:
            return _get_branch_head(conn, game_id, branch_id)
    except WorldStoreError:
        raise
    except sqlite3.Error as exc:
        raise WorldStorageError() from exc


def load_branch_head(game_id: GameId, branch_id: BranchId) -> WorldVersionSnapshot:
    try:
        with closing(_connect()) as conn:
            head = _get_branch_head(conn, game_id, branch_id)
            return _load_version(conn, head.version_id)
    except WorldStoreError:
        raise
    except sqlite3.Error as exc:
        raise WorldStorageError() from exc


def list_versions(game_id: GameId, branch_id: BranchId) -> list[WorldVersionRef]:
    try:
        with closing(_connect()) as conn:
            rows = conn.execute(
                """
                SELECT id, game_id, branch_id, parent_version_id, settlement_id,
                       created_at, protected
                FROM versions
                WHERE game_id = ? AND branch_id = ?
                ORDER BY created_at, id
                """,
                (str(game_id), str(branch_id)),
            ).fetchall()
        return [_row_to_version_ref(row) for row in rows]
    except sqlite3.Error as exc:
        raise WorldStorageError() from exc


def list_settlements(game_id: GameId, branch_id: BranchId) -> list[SettlementFacts]:
    try:
        with closing(_connect()) as conn:
            rows = conn.execute(
                """
                SELECT facts_json FROM settlements
                WHERE game_id = ? AND branch_id = ?
                ORDER BY created_at, id
                """,
                (str(game_id), str(branch_id)),
            ).fetchall()
        return [SettlementFacts.model_validate_json(row["facts_json"]) for row in rows]
    except (ValidationError, ValueError, TypeError) as exc:
        raise WorldCorruptDataError("stored settlement is invalid") from exc
    except sqlite3.Error as exc:
        raise WorldStorageError() from exc


def _row_to_action_request(row: sqlite3.Row) -> ActionRequestRecord:
    return ActionRequestRecord.model_validate(
        {
            "game_id": row["game_id"],
            "branch_id": row["branch_id"],
            "client_action_id": row["client_action_id"],
            "expected_parent_version_id": row["expected_parent_version_id"],
            "payload_hash": row["payload_hash"],
            "status": row["status"],
            "settlement_id": row["settlement_id"],
            "version_id": row["version_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        },
    )


def _find_action_request(
    conn: sqlite3.Connection,
    game_id: GameId | str,
    branch_id: BranchId | str,
    client_action_id: ClientActionId | str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT game_id, branch_id, client_action_id,
               expected_parent_version_id, payload_hash, status,
               settlement_id, version_id, result_json, created_at, updated_at
        FROM action_requests
        WHERE game_id = ? AND branch_id = ? AND client_action_id = ?
        """,
        (str(game_id), str(branch_id), str(client_action_id)),
    ).fetchone()


def get_action_request(
    game_id: GameId,
    branch_id: BranchId,
    client_action_id: ClientActionId,
) -> ActionRequestRecord | None:
    try:
        with closing(_connect()) as conn:
            row = _find_action_request(conn, game_id, branch_id, client_action_id)
        return _row_to_action_request(row) if row is not None else None
    except (ValidationError, ValueError, TypeError) as exc:
        raise WorldCorruptDataError("stored action request is invalid") from exc
    except sqlite3.Error as exc:
        raise WorldStorageError() from exc


def replay_action_request(intent: ActionIntent) -> SettlementCommitResult | None:
    """Return a completed idempotent result before invoking an AI provider.

    Absence means the caller may adjudicate. A conflicting or pending row keeps
    the same typed semantics as commit_settlement; the final transaction still
    rechecks this lookup to arbitrate concurrent requests.
    """

    try:
        with closing(_connect()) as conn:
            row = _find_action_request(
                conn,
                intent.game_id,
                intent.branch_id,
                intent.client_action_id,
            )
            if row is None:
                return None
            return _replay_or_reject(row, intent, intent.payload_hash())
    except WorldStoreError:
        raise
    except sqlite3.Error as exc:
        raise WorldStorageError() from exc


def _insert_action_request(
    conn: sqlite3.Connection,
    intent: ActionIntent,
    payload_hash: str,
    created_at: datetime,
) -> None:
    timestamp = created_at.isoformat()
    conn.execute(
        """
        INSERT INTO action_requests (
            game_id, branch_id, client_action_id,
            expected_parent_version_id, payload_hash, status,
            settlement_id, version_id, result_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL, ?, ?)
        """,
        (
            str(intent.game_id),
            str(intent.branch_id),
            str(intent.client_action_id),
            str(intent.expected_parent_version_id),
            payload_hash,
            timestamp,
            timestamp,
        ),
    )


def _insert_settlement(
    conn: sqlite3.Connection,
    facts: SettlementFacts,
) -> None:
    conn.execute(
        """
        INSERT INTO settlements (
            id, game_id, branch_id, client_action_id, parent_version_id,
            facts_json, delta_json, attribution_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(facts.settlement_id),
            str(facts.game_id),
            str(facts.branch_id),
            str(facts.client_action_id),
            str(facts.parent_version_id),
            facts.model_dump_json(),
            json.dumps(
                [delta.model_dump(mode="json") for delta in facts.deltas],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            facts.attribution.model_dump_json(),
            facts.committed_at.isoformat(),
        ),
    )


def _complete_action_request(
    conn: sqlite3.Connection,
    intent: ActionIntent,
    result: SettlementCommitResult,
    updated_at: datetime,
) -> None:
    cursor = conn.execute(
        """
        UPDATE action_requests
        SET status = 'completed', settlement_id = ?, version_id = ?,
            result_json = ?, updated_at = ?
        WHERE game_id = ? AND branch_id = ? AND client_action_id = ?
          AND status = 'pending'
        """,
        (
            str(result.facts.settlement_id),
            str(result.version.version_id),
            result.model_dump_json(),
            updated_at.isoformat(),
            str(intent.game_id),
            str(intent.branch_id),
            str(intent.client_action_id),
        ),
    )
    if cursor.rowcount != 1:
        raise WorldCorruptDataError("action request completion lost its pending row")


def _replay_or_reject(
    row: sqlite3.Row,
    intent: ActionIntent,
    payload_hash: str,
) -> SettlementCommitResult:
    if (
        row["expected_parent_version_id"] != str(intent.expected_parent_version_id)
        or row["payload_hash"] != payload_hash
    ):
        raise IdempotencyConflictError()
    if row["status"] != "completed" or not row["result_json"]:
        raise ActionInProgressError()
    try:
        stored = SettlementCommitResult.model_validate_json(row["result_json"])
    except (ValidationError, ValueError, TypeError) as exc:
        raise WorldCorruptDataError("stored action result is invalid") from exc
    return stored.model_copy(update={"replayed": True})


def _validate_registry_continuity(previous: GameState, changed: GameState) -> None:
    missing_entity_ids = set(previous.entity_registry).difference(changed.entity_registry)
    if missing_entity_ids:
        raise WorldCorruptDataError(
            "committed state cannot remove identities from the entity registry",
        )

    previous_player_id = previous.player_world_status.player_character_id
    changed_player_id = changed.player_world_status.player_character_id
    if previous_player_id is not None and changed_player_id != previous_player_id:
        raise WorldCorruptDataError(
            "committed state cannot replace or clear the player-character identity",
        )
    if changed_player_id is not None and not isinstance(
        changed.entity_registry.get(changed_player_id),
        PersonEntity,
    ):
        raise WorldCorruptDataError(
            "committed player_character_id must reference a person entity",
        )


def commit_settlement(
    intent: ActionIntent,
    state: GameState,
    proposal: AdjudicationProposal,
) -> SettlementCommitResult:
    """Commit one action request, settlement, snapshot, and head advance.

    The legal ``result_tier='failure'`` is committed like any other adjudicated
    result. Provider/schema failures never call this function. The branch head
    is checked again under ``BEGIN IMMEDIATE`` so stale proposals cannot land.
    """

    payload_hash = intent.payload_hash()
    settlement_id = new_settlement_id()
    version_id = new_version_id()
    committed_at = _utc_now()

    with closing(_connect()) as conn:
        try:
            _begin(conn)
            existing = _find_action_request(
                conn,
                intent.game_id,
                intent.branch_id,
                intent.client_action_id,
            )
            if existing is not None:
                result = _replay_or_reject(existing, intent, payload_hash)
                conn.commit()
                return result

            head = _get_branch_head(conn, intent.game_id, intent.branch_id)
            if head.version_id != intent.expected_parent_version_id:
                raise StaleParentVersionError(
                    intent.expected_parent_version_id,
                    head.version_id,
                )
            previous_state = _load_version(conn, head.version_id).state
            _validate_registry_continuity(previous_state, state)

            _insert_action_request(conn, intent, payload_hash, committed_at)
            attribution = SettlementAttribution(
                requested_executor_id=proposal.requested_executor_id,
                actual_executor_id=proposal.actual_executor_id,
                execution_status=proposal.execution_status,
                provider=proposal.provider,
            )
            facts = SettlementFacts(
                settlement_id=settlement_id,
                game_id=intent.game_id,
                branch_id=intent.branch_id,
                client_action_id=intent.client_action_id,
                parent_version_id=intent.expected_parent_version_id,
                result_version_id=version_id,
                payload_hash=payload_hash,
                result_tier=proposal.result_tier,
                key_factors=proposal.key_factors,
                immediate_changes=proposal.immediate_changes,
                long_term_risks=proposal.long_term_risks,
                new_opportunities=proposal.new_opportunities,
                deltas=proposal.deltas,
                attribution=attribution,
                committed_at=committed_at,
            )
            version = WorldVersionRef(
                game_id=intent.game_id,
                branch_id=intent.branch_id,
                version_id=version_id,
                parent_version_id=intent.expected_parent_version_id,
                settlement_id=settlement_id,
                created_at=committed_at,
            )
            snapshot = _snapshot_for_version(
                state,
                game_id=intent.game_id,
                branch_id=intent.branch_id,
                version_id=version_id,
                source_kind="settlement",
                source_ref=str(settlement_id),
            )

            _insert_settlement(conn, facts)
            _insert_version(conn, ref=version, state=snapshot, source_kind="settlement")
            if not _advance_branch_head(
                conn,
                game_id=intent.game_id,
                branch_id=intent.branch_id,
                expected_version_id=intent.expected_parent_version_id,
                next_version_id=version_id,
            ):
                current = _get_branch_head(conn, intent.game_id, intent.branch_id)
                raise StaleParentVersionError(
                    intent.expected_parent_version_id,
                    current.version_id,
                )

            result = SettlementCommitResult(version=version, facts=facts)
            _complete_action_request(conn, intent, result, committed_at)
            conn.commit()
            return result
        except WorldStoreError:
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise WorldStorageError() from exc
        except Exception:
            conn.rollback()
            raise


def _project_legacy_lists_to_registry(
    state: GameState,
    *,
    version_id: VersionId,
    source: EntitySource,
) -> dict[EntityId, WorldEntity]:
    registry: dict[EntityId, WorldEntity] = {}
    faction_ids: dict[str, EntityId] = {}

    for faction in state.factions:
        if faction.name in faction_ids:
            raise WorldCorruptDataError(
                "legacy faction names must be unique before registry projection",
            )
        entity_id = new_entity_id()
        faction_ids[faction.name] = entity_id
        registry[entity_id] = FactionEntity(
            entity_id=entity_id,
            display_name=faction.name,
            origin_version_id=version_id,
            source=source,
            influence=faction.influence,
        )

    minister_names: set[str] = set()
    for minister in state.ministers:
        if minister.name in minister_names:
            raise WorldCorruptDataError(
                "legacy minister names must be unique before registry projection",
            )
        minister_names.add(minister.name)
        entity_id = new_entity_id()
        status_value = getattr(minister.status, "value", str(minister.status))
        registry[entity_id] = PersonEntity(
            entity_id=entity_id,
            display_name=minister.name,
            legacy_name=minister.name,
            status=(
                "active"
                if status_value in {"active", "idle", "on_mission"}
                else "inactive"
            ),
            origin_version_id=version_id,
            source=source,
            faction_ids=(
                [faction_ids[minister.faction]]
                if minister.faction in faction_ids
                else []
            ),
            roles=list(minister.positions),
            available=status_value in {"active", "idle", "on_mission"},
        )

    region_names: set[str] = set()
    for region in state.regions:
        if region.name in region_names:
            raise WorldCorruptDataError(
                "legacy region names must be unique before registry projection",
            )
        region_names.add(region.name)
        entity_id = new_entity_id()
        registry[entity_id] = RegionEntity(
            entity_id=entity_id,
            display_name=region.name,
            legacy_name=region.name,
            origin_version_id=version_id,
            source=source,
        )

    return registry


def _bootstrap_entity_registry(
    state: GameState,
    *,
    version_id: VersionId,
    source: EntitySource,
    player_identity_summary: str,
) -> None:
    """Project unmigrated legacy lists once without replacing runtime entities."""

    if not state.entity_registry:
        state.entity_registry = _project_legacy_lists_to_registry(
            state,
            version_id=version_id,
            source=source,
        )

    for entity_id, entity in list(state.entity_registry.items()):
        if entity.entity_id != entity_id:
            raise WorldCorruptDataError(
                "entity registry key must match the embedded entity_id",
            )
        if entity.origin_version_id is None:
            state.entity_registry[entity_id] = entity.model_copy(
                update={"origin_version_id": version_id},
            )

    player_id = state.player_world_status.player_character_id
    if player_id is not None:
        player = state.entity_registry.get(player_id)
        if not isinstance(player, PersonEntity):
            raise WorldCorruptDataError(
                "player_character_id must reference a person in the entity registry",
            )
        return

    player_candidates = [
        entity.entity_id
        for entity in state.entity_registry.values()
        if isinstance(entity, PersonEntity) and "player_character" in entity.roles
    ]
    if len(player_candidates) > 1:
        raise WorldCorruptDataError(
            "entity registry contains multiple player-character candidates",
        )
    if player_candidates:
        player_id = player_candidates[0]
    else:
        player_id = new_entity_id()
        player_name = next(iter(state.character_sheets), "主角")
        state.entity_registry[player_id] = PersonEntity(
            entity_id=player_id,
            display_name=player_name,
            legacy_name=player_name,
            origin_version_id=version_id,
            source=source,
            roles=["player_character"],
        )

    identity_summary = state.player_world_status.identity_summary or player_identity_summary
    state.player_world_status = state.player_world_status.model_copy(
        update={
            "player_character_id": player_id,
            "identity_summary": identity_summary,
        },
    )


def _insert_legacy_import(
    conn: sqlite3.Connection,
    *,
    save_id: int,
    game_id: GameId,
    branch_id: BranchId,
    version_id: VersionId,
    source_row: sqlite3.Row,
    source_state_bytes: bytes,
    source_state_hash: str,
    metadata_json: str,
    imported_at: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO legacy_save_imports (
            save_id, game_id, branch_id, version_id,
            source_name, source_game_time, source_created_at,
            source_state_bytes, source_state_hash,
            migration_metadata_json, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            save_id,
            str(game_id),
            str(branch_id),
            str(version_id),
            source_row["name"],
            source_row["game_time"],
            source_row["created_at"],
            source_state_bytes,
            source_state_hash,
            metadata_json,
            imported_at.isoformat(),
        ),
    )


def _existing_legacy_import(
    conn: sqlite3.Connection,
    save_id: int,
) -> LegacyWorldImportResult | None:
    row = conn.execute(
        """
        SELECT version_id, source_state_hash, migration_metadata_json
        FROM legacy_save_imports WHERE save_id = ?
        """,
        (save_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        metadata = json.loads(row["migration_metadata_json"])
        notes = tuple(str(note) for note in metadata.get("notes", []))
        snapshot = _load_version(conn, row["version_id"])
    except (json.JSONDecodeError, TypeError, AttributeError) as exc:
        raise WorldCorruptDataError("legacy import ledger is invalid") from exc
    return LegacyWorldImportResult(
        version=snapshot.ref,
        state=snapshot.state,
        migration_notes=notes,
        source_state_hash=row["source_state_hash"],
        replayed=True,
    )


def import_legacy_save(save_id: int) -> LegacyWorldImportResult:
    """Import one legacy row without updating or deleting it.

    The decoded copy is migrated in memory. The source bytes, migration notes,
    protected root graph, and idempotency ledger are committed together.
    """

    from .saves import _migrate_save

    with closing(_connect()) as conn:
        try:
            _begin(conn)
            existing = _existing_legacy_import(conn, save_id)
            if existing is not None:
                conn.commit()
                return existing

            source_row = conn.execute(
                """
                SELECT id, name, game_time, created_at, state_json
                FROM saves WHERE id = ?
                """,
                (save_id,),
            ).fetchone()
            if source_row is None:
                raise LegacySaveNotFoundError(save_id)

            raw_state = source_row["state_json"]
            if not isinstance(raw_state, str):
                raise LegacySaveCorruptError(save_id)
            source_state_bytes = raw_state.encode("utf-8")
            source_state_hash = hashlib.sha256(source_state_bytes).hexdigest()
            try:
                decoded = json.loads(raw_state)
                if not isinstance(decoded, dict):
                    raise TypeError("legacy state root must be an object")
                notes = _migrate_save(decoded)
                state = GameState.model_validate(decoded)
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
                raise LegacySaveCorruptError(save_id) from exc

            imported_at = _utc_now()
            game_id = new_game_id()
            branch_id = new_branch_id()
            version_id = new_version_id()
            _bootstrap_entity_registry(
                state,
                version_id=version_id,
                source=EntitySource(
                    kind="legacy_save",
                    reference=str(save_id),
                    summary="Imported from an immutable legacy save snapshot",
                ),
                player_identity_summary="Imported player character",
            )
            ref, snapshot = _create_root_in_transaction(
                conn,
                state,
                game_id=game_id,
                branch_id=branch_id,
                version_id=version_id,
                created_at=imported_at,
                protected=True,
                source_kind="legacy_save",
                source_ref=str(save_id),
                imported_at=imported_at,
                migration_notes=notes,
            )
            metadata_json = json.dumps(
                {
                    "schema_version": 1,
                    "migration_applied": bool(notes),
                    "notes": notes,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            _insert_legacy_import(
                conn,
                save_id=save_id,
                game_id=game_id,
                branch_id=branch_id,
                version_id=version_id,
                source_row=source_row,
                source_state_bytes=source_state_bytes,
                source_state_hash=source_state_hash,
                metadata_json=metadata_json,
                imported_at=imported_at,
            )
            conn.commit()
            return LegacyWorldImportResult(
                version=ref,
                state=snapshot,
                migration_notes=tuple(notes),
                source_state_hash=source_state_hash,
            )
        except WorldStoreError:
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise WorldStorageError() from exc
        except Exception:
            conn.rollback()
            raise


class WorldStoreError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class WorldStorageError(WorldStoreError):
    def __init__(self):
        super().__init__("world_storage_error", "世界状态提交失败，存储异常")


class WorldNotFoundError(WorldStoreError):
    def __init__(self, resource: str, identity: str):
        self.resource = resource
        self.identity = identity
        super().__init__("world_not_found", f"{resource} {identity} not found")


class WorldCorruptDataError(WorldStoreError):
    def __init__(self, message: str):
        super().__init__("world_corrupt_data", message)


class IdempotencyConflictError(WorldStoreError):
    def __init__(self):
        super().__init__(
            "idempotency_conflict",
            "同一动作标识已用于不同的父版本或请求内容",
        )


class ActionInProgressError(WorldStoreError):
    def __init__(self):
        super().__init__("action_in_progress", "动作仍在处理中，请稍后重试")


class StaleParentVersionError(WorldStoreError):
    def __init__(self, expected: VersionId, current: VersionId):
        self.expected_parent_version_id = expected
        self.current_version_id = current
        super().__init__(
            "stale_parent_version",
            "提交所基于的世界版本已不是当前分支头",
        )


class LegacySaveNotFoundError(WorldStoreError):
    def __init__(self, save_id: int):
        self.save_id = save_id
        super().__init__("legacy_save_not_found", f"Legacy save {save_id} not found")


class LegacySaveCorruptError(WorldStoreError):
    def __init__(self, save_id: int):
        self.save_id = save_id
        super().__init__("legacy_save_corrupt", f"Legacy save {save_id} is corrupt")
