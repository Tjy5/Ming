from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import ValidationError

from .maintenance import coordinated_storage_write

from engine.tables import REGION_NAMES
from models.game import GameState
from models.settlement import (
    ActionIntent,
    ActionRequestRecord,
    AdjudicationProposal,
    PlayerWorldDelta,
    SettlementAttribution,
    SettlementCommitResult,
    SettlementFacts,
    TerminalRecordFacts,
)
from models.world import (
    ASSEMBLY_PARTICIPATE_CAPABILITY,
    ENTITY_DIALOGUE_CAPABILITY,
    MEMORIAL_SUBMIT_CAPABILITY,
    OFFICE_APPOINTABLE_CAPABILITY,
    ActivityId,
    BookmarkId,
    BranchId,
    ClientActionId,
    CheckpointId,
    EntityId,
    EntitySource,
    ElapsedSegmentPlan,
    FactionEntity,
    GameId,
    PersonEntity,
    PermissionReference,
    RegionEntity,
    SettlementId,
    TerminalRecordId,
    VersionId,
    WorldSnapshotMetadata,
    WorldBranchRef,
    WorldEntity,
    WorldVersionRef,
    WorldBookmarkRef,
    new_branch_id,
    new_entity_id,
    new_game_id,
    new_permission_id,
    new_settlement_id,
    new_terminal_record_id,
    new_version_id,
)
from models.world_state import AppliedMetricAttribution, ExecutorFacts, RollRecord


_INITIAL_ENTITY_SOURCE_REF = "yuanming-initial-v1"
MIN_RETENTION_RECENT_LIMIT = 1
MAX_RETENTION_RECENT_LIMIT = 1000


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


@dataclass(frozen=True)
class RetentionPlan:
    """Report-only retention decision for an immutable world graph.

    The planner intentionally performs no writes.  Callers can inspect the
    protected/restore/delete sets and present the report before enabling a
    future transactional garbage collector.
    """

    game_id: GameId
    branch_id: BranchId | None
    recent_limit: int
    protected_version_ids: tuple[VersionId, ...]
    monthly_recovery_version_ids: tuple[VersionId, ...]
    delete_version_ids: tuple[VersionId, ...]
    reasons: dict[str, tuple[str, ...]]
    # These fields make the report self-describing for operators and callers
    # which decide whether to invoke the explicitly enabled collector.
    graph_version_count: int = 0
    shared_ancestor_version_ids: tuple[VersionId, ...] = ()
    mode: str = "report"

    @property
    def retained_version_ids(self) -> tuple[VersionId, ...]:
        ids = set(self.protected_version_ids)
        ids.update(self.monthly_recovery_version_ids)
        return tuple(sorted(ids, key=str))


@dataclass(frozen=True)
class RetentionGCResult:
    """Outcome of an explicitly enabled, transactional retention collection."""

    audit_id: str
    plan: RetentionPlan
    deleted_version_ids: tuple[VersionId, ...] = ()
    deleted_settlement_ids: tuple[SettlementId, ...] = ()
    blocked_version_ids: tuple[VersionId, ...] = ()
    enabled: bool = False
    committed: bool = False

    @property
    def deleted_count(self) -> int:
        return len(self.deleted_version_ids)


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
                -- Nullable after retention compaction: a retained full snapshot
                -- may be detached from a deleted historical ancestor.
                parent_version_id TEXT,
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

            CREATE TABLE IF NOT EXISTS retention_gc_audits (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                branch_id TEXT,
                recent_limit INTEGER NOT NULL,
                mode TEXT NOT NULL,
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                committed INTEGER NOT NULL CHECK (committed IN (0, 1)),
                planned_version_ids_json TEXT NOT NULL,
                protected_version_ids_json TEXT NOT NULL,
                monthly_recovery_version_ids_json TEXT NOT NULL,
                deleted_version_ids_json TEXT NOT NULL,
                blocked_version_ids_json TEXT NOT NULL,
                reasons_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE RESTRICT
            );

            CREATE INDEX IF NOT EXISTS idx_versions_branch_created
                ON versions(game_id, branch_id, created_at, id);
            CREATE INDEX IF NOT EXISTS idx_settlements_branch_created
                ON settlements(game_id, branch_id, created_at, id);
            CREATE INDEX IF NOT EXISTS idx_action_requests_status
                ON action_requests(game_id, branch_id, status);
            CREATE INDEX IF NOT EXISTS idx_retention_gc_audits_game_created
                ON retention_gc_audits(game_id, created_at, id);
            """,
        )
        conn.commit()

        # Older installations created ``settlements.parent_version_id`` as
        # NOT NULL before retention compaction was introduced.  SQLite cannot
        # alter a column's nullability in place, so perform a small additive
        # forward migration once, preserving every row and constraint.  This
        # keeps transactional GC usable after upgrading an existing save DB;
        # fresh databases already have the nullable definition above.
        columns = conn.execute("PRAGMA table_info(settlements)").fetchall()
        parent_column = next(
            (row for row in columns if row["name"] == "parent_version_id"),
            None,
        )
        if parent_column is not None and int(parent_column["notnull"] or 0) == 1:
            conn.execute("PRAGMA foreign_keys = OFF")
            try:
                conn.execute("BEGIN")
                conn.execute(
                    """
                    CREATE TABLE settlements__nullable (
                        id TEXT PRIMARY KEY,
                        game_id TEXT NOT NULL,
                        branch_id TEXT NOT NULL,
                        client_action_id TEXT NOT NULL,
                        parent_version_id TEXT,
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
                    )
                    """,
                )
                conn.execute(
                    """
                    INSERT INTO settlements__nullable (
                        id, game_id, branch_id, client_action_id,
                        parent_version_id, facts_json, delta_json,
                        attribution_json, created_at
                    )
                    SELECT id, game_id, branch_id, client_action_id,
                           parent_version_id, facts_json, delta_json,
                           attribution_json, created_at
                    FROM settlements
                    """,
                )
                conn.execute("DROP TABLE settlements")
                conn.execute("ALTER TABLE settlements__nullable RENAME TO settlements")
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_settlements_branch_created
                        ON settlements(game_id, branch_id, created_at, id)
                    """,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")


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


@coordinated_storage_write
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


@coordinated_storage_write
def create_branch_from_version(version_id: VersionId) -> WorldVersionRef:
    """Atomically fork an immutable version into a new active branch root."""
    source = load_version(version_id)
    # A committed death is a durable terminal for this branch. Players may
    # branch from the protected pre-death recovery version, but the terminal
    # snapshot itself cannot become a playable root.
    if source.state.player_world_status.life_status == "dead":
        raise WorldTerminalStateError()
    branch_id = new_branch_id()
    root_version_id = new_version_id()
    created_at = _utc_now()

    from engine.activity import rebase_pending_checkpoints

    rebased = rebase_pending_checkpoints(source.state, root_version_id)
    snapshot = _snapshot_for_version(
        rebased,
        game_id=source.ref.game_id,
        branch_id=branch_id,
        version_id=root_version_id,
        source_kind="fork",
        source_ref=str(source.ref.version_id),
    )
    ref = WorldVersionRef(
        game_id=source.ref.game_id,
        branch_id=branch_id,
        version_id=root_version_id,
        parent_version_id=source.ref.version_id,
        created_at=created_at,
    )

    with closing(_connect()) as conn:
        try:
            _begin(conn)
            conn.execute(
                """
                INSERT INTO branches (
                    id, game_id, parent_branch_id, forked_from_version_id,
                    head_version_id, created_at, status
                ) VALUES (?, ?, ?, ?, NULL, ?, 'active')
                """,
                (
                    str(branch_id),
                    str(source.ref.game_id),
                    str(source.ref.branch_id),
                    str(source.ref.version_id),
                    created_at.isoformat(),
                ),
            )
            _insert_version(conn, ref=ref, state=snapshot, source_kind="fork")
            if not _advance_branch_head(
                conn,
                game_id=ref.game_id,
                branch_id=ref.branch_id,
                expected_version_id=None,
                next_version_id=ref.version_id,
            ):
                raise WorldCorruptDataError("forked branch rejected its root version")
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


def _row_to_branch_ref(row: sqlite3.Row) -> WorldBranchRef:
    return WorldBranchRef.model_validate(
        {
            "game_id": row["game_id"],
            "branch_id": row["id"],
            "parent_branch_id": row["parent_branch_id"],
            "forked_from_version_id": row["forked_from_version_id"],
            "head_version_id": row["head_version_id"],
            "created_at": row["created_at"],
            "status": row["status"],
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


def _get_branch(
    conn: sqlite3.Connection,
    game_id: GameId | str,
    branch_id: BranchId | str,
) -> WorldBranchRef:
    row = conn.execute(
        """
        SELECT id, game_id, parent_branch_id, forked_from_version_id,
               head_version_id, created_at, status
        FROM branches
        WHERE game_id = ? AND id = ?
        """,
        (str(game_id), str(branch_id)),
    ).fetchone()
    if row is None:
        raise WorldNotFoundError("branch", str(branch_id))
    try:
        return _row_to_branch_ref(row)
    except (ValidationError, ValueError, TypeError) as exc:
        raise WorldCorruptDataError("stored world branch is invalid") from exc


def get_branch(game_id: GameId, branch_id: BranchId) -> WorldBranchRef:
    try:
        with closing(_connect()) as conn:
            return _get_branch(conn, game_id, branch_id)
    except WorldStoreError:
        raise
    except sqlite3.Error as exc:
        raise WorldStorageError() from exc


def list_branches(game_id: GameId) -> list[WorldBranchRef]:
    try:
        with closing(_connect()) as conn:
            rows = conn.execute(
                """
                SELECT id, game_id, parent_branch_id, forked_from_version_id,
                       head_version_id, created_at, status
                FROM branches
                WHERE game_id = ?
                ORDER BY created_at, id
                """,
                (str(game_id),),
            ).fetchall()
            if not rows:
                game = conn.execute(
                    "SELECT id FROM games WHERE id = ?",
                    (str(game_id),),
                ).fetchone()
                if game is None:
                    raise WorldNotFoundError("game", str(game_id))
        return [_row_to_branch_ref(row) for row in rows]
    except WorldStoreError:
        raise
    except (ValidationError, ValueError, TypeError) as exc:
        raise WorldCorruptDataError("stored world branch is invalid") from exc
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
            if not rows:
                branch = conn.execute(
                    "SELECT id FROM branches WHERE game_id = ? AND id = ?",
                    (str(game_id), str(branch_id)),
                ).fetchone()
                if branch is None:
                    raise WorldNotFoundError("branch", str(branch_id))
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


def get_settlement(settlement_id: SettlementId) -> SettlementFacts:
    try:
        with closing(_connect()) as conn:
            row = conn.execute(
                "SELECT facts_json FROM settlements WHERE id = ?",
                (str(settlement_id),),
            ).fetchone()
        if row is None:
            raise WorldNotFoundError("settlement", str(settlement_id))
        return SettlementFacts.model_validate_json(row["facts_json"])
    except WorldStoreError:
        raise
    except (ValidationError, ValueError, TypeError) as exc:
        raise WorldCorruptDataError("stored settlement is invalid") from exc
    except sqlite3.Error as exc:
        raise WorldStorageError() from exc


@coordinated_storage_write
def create_bookmark(
    game_id: GameId,
    branch_id: BranchId,
    version_id: VersionId,
    name: str,
) -> WorldBookmarkRef:
    """Create a durable bookmark for an existing version in one branch."""
    bookmark_id = BookmarkId(uuid4())
    created_at = _utc_now()
    with closing(_connect()) as conn:
        try:
            _begin(conn)
            row = conn.execute(
                "SELECT id FROM versions WHERE id = ? AND game_id = ? AND branch_id = ?",
                (str(version_id), str(game_id), str(branch_id)),
            ).fetchone()
            if row is None:
                raise WorldNotFoundError("version", str(version_id))
            conn.execute(
                "INSERT INTO bookmarks (id, game_id, branch_id, version_id, name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(bookmark_id), str(game_id), str(branch_id), str(version_id), name.strip(), created_at.isoformat()),
            )
            conn.commit()
        except WorldStoreError:
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise WorldStorageError() from exc
    return WorldBookmarkRef(
        bookmark_id=bookmark_id, game_id=game_id, branch_id=branch_id,
        version_id=version_id, name=name.strip(), created_at=created_at,
    )


@coordinated_storage_write
def delete_bookmark(bookmark_id: BookmarkId, *, game_id: GameId | None = None) -> None:
    with closing(_connect()) as conn:
        try:
            _begin(conn)
            if game_id is None:
                cur = conn.execute("DELETE FROM bookmarks WHERE id = ?", (str(bookmark_id),))
            else:
                cur = conn.execute(
                    "DELETE FROM bookmarks WHERE id = ? AND game_id = ?",
                    (str(bookmark_id), str(game_id)),
                )
            if cur.rowcount == 0:
                raise WorldNotFoundError("bookmark", str(bookmark_id))
            conn.commit()
        except WorldStoreError:
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise WorldStorageError() from exc


def list_bookmarks(
    game_id: GameId,
    branch_id: BranchId | None = None,
) -> list[WorldBookmarkRef]:
    """List durable version bookmarks, optionally scoped to one branch."""
    try:
        with closing(_connect()) as conn:
            if branch_id is None:
                rows = conn.execute(
                    """
                    SELECT id, game_id, branch_id, version_id, name, created_at
                    FROM bookmarks WHERE game_id = ? ORDER BY created_at, id
                    """,
                    (str(game_id),),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, game_id, branch_id, version_id, name, created_at
                    FROM bookmarks WHERE game_id = ? AND branch_id = ?
                    ORDER BY created_at, id
                    """,
                    (str(game_id), str(branch_id)),
                ).fetchall()
            if branch_id is not None and not rows:
                branch = conn.execute(
                    "SELECT id FROM branches WHERE game_id = ? AND id = ?",
                    (str(game_id), str(branch_id)),
                ).fetchone()
                if branch is None:
                    raise WorldNotFoundError("branch", str(branch_id))
        return [
            WorldBookmarkRef(
                bookmark_id=BookmarkId(row["id"]),
                game_id=GameId(row["game_id"]),
                branch_id=BranchId(row["branch_id"]),
                version_id=VersionId(row["version_id"]),
                name=row["name"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
    except WorldStoreError:
        raise
    except (ValidationError, ValueError, TypeError) as exc:
        raise WorldCorruptDataError("stored bookmark is invalid") from exc
    except sqlite3.Error as exc:
        raise WorldStorageError() from exc


def _retention_plan_in_transaction(
    conn: sqlite3.Connection,
    game_id: GameId,
    branch_id: BranchId | None,
    recent_limit: int,
) -> RetentionPlan:
    """Compute a graph-wide plan using the caller's open transaction.

    Retention is reference-aware across *all* branches in a game.  A selected
    branch may only contribute candidates, but any root, head, bookmark,
    terminal predecessor, or shared descendant retained by another branch is
    protected globally. Same-branch historical edges can be detached during
    commit because every snapshot stores a complete recoverable state.
    """
    branch_rows = conn.execute(
        """
        SELECT id, game_id, parent_branch_id, forked_from_version_id,
               head_version_id, created_at, status
        FROM branches WHERE game_id = ? ORDER BY created_at, id
        """,
        (str(game_id),),
    ).fetchall()
    if not branch_rows:
        raise WorldNotFoundError("game", str(game_id))
    all_branches = [_row_to_branch_ref(row) for row in branch_rows]
    selected = [
        branch for branch in all_branches
        if branch_id is None or branch.branch_id == branch_id
    ]
    if branch_id is not None and not selected:
        raise WorldNotFoundError("branch", str(branch_id))

    versions_rows = conn.execute(
        """
        SELECT id, game_id, branch_id, parent_version_id, settlement_id,
               state_json, created_at, protected
        FROM versions WHERE game_id = ? ORDER BY created_at, id
        """,
        (str(game_id),),
    ).fetchall()
    by_id = {str(row["id"]): row for row in versions_rows}
    # SQLite yields strings while Pydantic may yield UUID-backed NewTypes.
    # Canonicalize graph keys to strings internally to avoid mixed-set misses.
    protected: set[str] = set()
    monthly: set[str] = set()
    reasons: dict[str, set[str]] = {}

    def protect(version: VersionId | str, reason: str) -> None:
        key = str(version)
        if key not in by_id:
            # A dangling reference is graph corruption, never a deletion hint.
            raise WorldCorruptDataError(f"retention reference points to unknown version {key}")
        protected.add(key)
        reasons.setdefault(key, set()).add(reason)

    # Durable references and branch roots/heads are always retained globally.
    for row in versions_rows:
        version = str(row["id"])
        if row["protected"]:
            protect(version, "database_protected")
        if row["parent_version_id"] is None:
            protect(version, "branch_root")
    for branch in all_branches:
        if branch.head_version_id is not None:
            protect(branch.head_version_id, "branch_head")
        if branch.forked_from_version_id is not None:
            protect(branch.forked_from_version_id, "branch_fork_root")
        # The first node belonging to a branch is its immutable branch root,
        # including a fork root whose parent lives on another branch.
        root = conn.execute(
            """
            SELECT id FROM versions WHERE game_id = ? AND branch_id = ?
            ORDER BY created_at, id LIMIT 1
            """,
            (str(game_id), str(branch.branch_id)),
        ).fetchone()
        if root is not None:
            protect(root["id"], "branch_root")

    for row in conn.execute("SELECT version_id FROM bookmarks WHERE game_id = ?", (str(game_id),)):
        protect(row["version_id"], "bookmark")
    for row in conn.execute(
        "SELECT version_id, previous_version_id FROM terminal_records WHERE game_id = ?",
        (str(game_id),),
    ):
        protect(row["version_id"], "terminal_version")
        protect(row["previous_version_id"], "terminal_predecessor")

    # Recent and monthly recovery points only contribute candidates/protection
    # for the requested branch scope; references above remain graph-wide.
    selected_ids = {str(item.branch_id) for item in selected}
    by_branch: dict[str, list[sqlite3.Row]] = {}
    for row in versions_rows:
        if row["branch_id"] in selected_ids:
            by_branch.setdefault(row["branch_id"], []).append(row)
    for rows in by_branch.values():
        action_rows = [row for row in rows if row["settlement_id"] is not None]
        for row in action_rows[-recent_limit:]:
            protect(row["id"], "recent_action")
        month_last: dict[tuple[int, int], sqlite3.Row] = {}
        older = action_rows[:-recent_limit] if recent_limit < len(action_rows) else []
        for row in older:
            try:
                state = GameState.model_validate_json(row["state_json"])
                projection = state.time.calendar
                if projection is None:
                    raise ValueError("version has no calendar projection")
                key = (projection.year, projection.month)
            except Exception:
                key = (0, 0)
            month_last[key] = row
        for row in month_last.values():
            version = str(row["id"])
            if version not in protected:
                monthly.add(version)
                reasons.setdefault(version, set()).add("monthly_recovery")

    # Shared ancestors (nodes referenced by more than one branch) are retained
    # globally. Ordinary same-branch ancestors can be detached during the
    # transactional compaction below because snapshots are complete recoverable
    # states; preserving every linear parent would make GC impossible.
    child_branches: dict[str, set[str]] = {}
    for row in versions_rows:
        parent = row["parent_version_id"]
        if parent is not None:
            child_branches.setdefault(str(parent), set()).add(str(row["branch_id"]))
    for parent, branch_set in child_branches.items():
        if len(branch_set) > 1:
            protect(parent, "shared_ancestor")

    retained = protected | monthly
    delete = {
        str(row["id"])
        for row in versions_rows
        if row["branch_id"] in selected_ids and str(row["id"]) not in retained
    }
    shared = tuple(
        sorted(
            (VersionId(version) for version, branch_set in child_branches.items() if len(branch_set) > 1),
            key=str,
        )
    )
    return RetentionPlan(
        game_id=game_id,
        branch_id=branch_id,
        recent_limit=recent_limit,
        protected_version_ids=tuple(VersionId(value) for value in sorted(protected)),
        monthly_recovery_version_ids=tuple(VersionId(value) for value in sorted(monthly)),
        delete_version_ids=tuple(VersionId(value) for value in sorted(delete)),
        reasons={key: tuple(sorted(value)) for key, value in reasons.items()},
        graph_version_count=len(versions_rows),
        shared_ancestor_version_ids=shared,
    )


def plan_retention(
    game_id: GameId,
    branch_id: BranchId | None = None,
    *,
    recent_limit: int = 100,
) -> RetentionPlan:
    """Build a report-only, reference-aware retention plan (never deletes)."""
    if (
        isinstance(recent_limit, bool)
        or not isinstance(recent_limit, int)
        or not MIN_RETENTION_RECENT_LIMIT <= recent_limit <= MAX_RETENTION_RECENT_LIMIT
    ):
        raise ValueError("recent_limit must be an integer from 1 to 1000")
    try:
        with closing(_connect()) as conn:
            return _retention_plan_in_transaction(conn, game_id, branch_id, recent_limit)
    except WorldStoreError:
        raise
    except (ValidationError, ValueError, TypeError) as exc:
        raise WorldCorruptDataError("stored retention graph is invalid") from exc
    except sqlite3.Error as exc:
        raise WorldStorageError() from exc


@coordinated_storage_write
def collect_retention(
    game_id: GameId,
    branch_id: BranchId | None = None,
    *,
    recent_limit: int = 100,
    enabled: bool = False,
) -> RetentionGCResult:
    """Collect report candidates only when the caller explicitly enables GC.

    Planning remains the default and is side-effect free.  ``enabled=True`` is
    the deliberate deletion path; planning, audit insertion, dependency checks,
    row deletion, and audit completion all run in one SQLite transaction.  Any
    failure rolls back the graph and leaves no misleading audit entry.
    """
    if (
        isinstance(recent_limit, bool)
        or not isinstance(recent_limit, int)
        or not MIN_RETENTION_RECENT_LIMIT <= recent_limit <= MAX_RETENTION_RECENT_LIMIT
    ):
        raise ValueError("recent_limit must be an integer from 1 to 1000")
    audit_id = str(uuid4())
    with closing(_connect()) as conn:
        try:
            _begin(conn)
            plan = _retention_plan_in_transaction(conn, game_id, branch_id, recent_limit)
            if not enabled:
                conn.rollback()
                return RetentionGCResult(audit_id=audit_id, plan=plan, enabled=False, committed=False)

            # Re-check every candidate against live references while holding the
            # write lock.  A candidate with any retained child or durable edge is
            # blocked and recorded rather than risking a partial graph delete.
            planned = set(plan.delete_version_ids)
            blocked: set[VersionId] = set()
            rows = conn.execute(
                "SELECT id, parent_version_id, settlement_id FROM versions WHERE game_id = ?",
                (str(game_id),),
            ).fetchall()
            for row in rows:
                version = VersionId(row["id"])
                if version not in planned:
                    continue
                children = conn.execute(
                    "SELECT id, branch_id FROM versions WHERE game_id = ? AND parent_version_id = ?",
                    (str(game_id), str(version)),
                ).fetchall()
                retained_children = [
                    child for child in children if VersionId(child["id"]) not in planned
                ]
                if retained_children:
                    # Cross-branch children are protected by the planner's
                    # shared-ancestor rule. Same-branch retained snapshots are
                    # complete states and may be detached in this transaction.
                    if len({str(child["branch_id"]) for child in retained_children}) > 1:
                        blocked.add(version)
                    else:
                        for child in retained_children:
                            conn.execute(
                                "UPDATE versions SET parent_version_id = NULL WHERE game_id = ? AND id = ?",
                                (str(game_id), str(child["id"])),
                            )
                            conn.execute(
                                "UPDATE settlements SET parent_version_id = NULL WHERE game_id = ? AND parent_version_id = ?",
                                (str(game_id), str(version)),
                            )
                if conn.execute(
                    "SELECT 1 FROM branches WHERE game_id = ? AND (head_version_id = ? OR forked_from_version_id = ?) LIMIT 1",
                    (str(game_id), str(version), str(version)),
                ).fetchone() is not None:
                    blocked.add(version)
                if conn.execute(
                    "SELECT 1 FROM bookmarks WHERE game_id = ? AND version_id = ? LIMIT 1",
                    (str(game_id), str(version)),
                ).fetchone() is not None:
                    blocked.add(version)
                if conn.execute(
                    "SELECT 1 FROM terminal_records WHERE game_id = ? AND (version_id = ? OR previous_version_id = ?) LIMIT 1",
                    (str(game_id), str(version), str(version)),
                ).fetchone() is not None:
                    blocked.add(version)
            delete_ids = tuple(sorted(planned - blocked, key=str))
            # UUID ordering is unrelated to graph depth. Detach every child of
            # a deletable full snapshot before row deletion so a long chain
            # cannot attempt to delete a parent ahead of its candidate child.
            for version in delete_ids:
                conn.execute(
                    "UPDATE versions SET parent_version_id = NULL WHERE game_id = ? AND parent_version_id = ?",
                    (str(game_id), str(version)),
                )
                conn.execute(
                    "UPDATE settlements SET parent_version_id = NULL WHERE game_id = ? AND parent_version_id = ?",
                    (str(game_id), str(version)),
                )
            deleted_settlements: list[SettlementId] = []
            for version in sorted(delete_ids, key=str, reverse=True):
                row = conn.execute(
                    "SELECT settlement_id FROM versions WHERE game_id = ? AND id = ?",
                    (str(game_id), str(version)),
                ).fetchone()
                if row is None:
                    raise WorldCorruptDataError(f"retention candidate {version} disappeared")
                settlement_id = row["settlement_id"]
                if settlement_id is not None:
                    conn.execute(
                        "DELETE FROM action_requests WHERE game_id = ? AND (version_id = ? OR settlement_id = ? OR expected_parent_version_id = ?)",
                        (str(game_id), str(version), str(settlement_id), str(version)),
                    )
                    # Break the version -> settlement FK before removing the
                    # settlement row; both records are retired as one unit.
                    conn.execute(
                        "UPDATE versions SET settlement_id = NULL WHERE game_id = ? AND id = ?",
                        (str(game_id), str(version)),
                    )
                    conn.execute(
                        "DELETE FROM settlements WHERE game_id = ? AND id = ?",
                        (str(game_id), str(settlement_id)),
                    )
                    deleted_settlements.append(SettlementId(settlement_id))
                else:
                    conn.execute(
                        "DELETE FROM action_requests WHERE game_id = ? AND expected_parent_version_id = ?",
                        (str(game_id), str(version)),
                    )
                deleted = conn.execute(
                    "DELETE FROM versions WHERE game_id = ? AND id = ?",
                    (str(game_id), str(version)),
                )
                if deleted.rowcount != 1:
                    raise WorldCorruptDataError(f"retention candidate {version} could not be deleted")

            now = _utc_now().isoformat()
            blocked_ids = tuple(sorted(blocked, key=str))
            audit_reasons = dict(plan.reasons)
            for version in blocked_ids:
                audit_reasons.setdefault(str(version), ())
                audit_reasons[str(version)] = tuple(sorted(set(audit_reasons[str(version)]) | {"blocked_live_reference"}))
            conn.execute(
                """
                INSERT INTO retention_gc_audits (
                    id, game_id, branch_id, recent_limit, mode, enabled, committed,
                    planned_version_ids_json, protected_version_ids_json,
                    monthly_recovery_version_ids_json, deleted_version_ids_json,
                    blocked_version_ids_json, reasons_json, created_at
                ) VALUES (?, ?, ?, ?, 'transactional_gc', 1, 1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    str(game_id),
                    str(branch_id) if branch_id is not None else None,
                    recent_limit,
                    json.dumps([str(item) for item in plan.delete_version_ids], sort_keys=True),
                    json.dumps([str(item) for item in plan.protected_version_ids], sort_keys=True),
                    json.dumps([str(item) for item in plan.monthly_recovery_version_ids], sort_keys=True),
                    json.dumps([str(item) for item in delete_ids], sort_keys=True),
                    json.dumps([str(item) for item in blocked_ids], sort_keys=True),
                    json.dumps(audit_reasons, sort_keys=True),
                    now,
                ),
            )
            conn.commit()
            committed_plan = RetentionPlan(
                **{**plan.__dict__, "mode": "transactional_gc"},
            )
            return RetentionGCResult(
                audit_id=audit_id,
                plan=committed_plan,
                deleted_version_ids=delete_ids,
                deleted_settlement_ids=tuple(sorted(deleted_settlements, key=str)),
                blocked_version_ids=blocked_ids,
                enabled=True,
                committed=True,
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


# Explicitly named alias for callers that prefer the garbage-collector term;
# both names retain the same ``enabled=False`` safety default.
garbage_collect_retention = collect_retention


def run_retention_gc(
    game_id: GameId,
    branch_id: BranchId | None = None,
    *,
    recent_limit: int = 100,
    enable: bool = False,
) -> RetentionGCResult:
    """Compatibility spelling with an explicit ``enable`` switch."""

    return collect_retention(
        game_id,
        branch_id,
        recent_limit=recent_limit,
        enabled=enable,
    )


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
            result = _replay_or_reject(row, intent, intent.payload_hash())
            _validate_terminal_replay(conn, result)
            return result
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


def _death_deltas(proposal: AdjudicationProposal) -> list[PlayerWorldDelta]:
    return [
        delta
        for delta in proposal.deltas
        if isinstance(delta, PlayerWorldDelta) and delta.operation == "death"
    ]


def _row_to_terminal_record(row: sqlite3.Row) -> TerminalRecordFacts:
    record = TerminalRecordFacts.model_validate_json(row["facts_json"])
    if (
        str(record.terminal_record_id) != row["id"]
        or str(record.game_id) != row["game_id"]
        or str(record.branch_id) != row["branch_id"]
        or str(record.settlement_id) != row["settlement_id"]
        or str(record.version_id) != row["version_id"]
        or str(record.previous_version_id) != row["previous_version_id"]
    ):
        raise WorldCorruptDataError("stored terminal record identity is inconsistent")
    return record


def _get_terminal_record(
    conn: sqlite3.Connection,
    settlement_id: SettlementId | str,
) -> TerminalRecordFacts | None:
    row = conn.execute(
        """
        SELECT id, game_id, branch_id, settlement_id, version_id,
               previous_version_id, facts_json, created_at
        FROM terminal_records
        WHERE settlement_id = ?
        """,
        (str(settlement_id),),
    ).fetchone()
    if row is None:
        return None
    try:
        return _row_to_terminal_record(row)
    except WorldStoreError:
        raise
    except (ValidationError, ValueError, TypeError) as exc:
        raise WorldCorruptDataError("stored terminal record is invalid") from exc


def get_terminal_record(settlement_id: SettlementId) -> TerminalRecordFacts:
    try:
        with closing(_connect()) as conn:
            record = _get_terminal_record(conn, settlement_id)
        if record is None:
            raise WorldNotFoundError("terminal_record", str(settlement_id))
        return record
    except WorldStoreError:
        raise
    except sqlite3.Error as exc:
        raise WorldStorageError() from exc


def _validate_terminal_replay(
    conn: sqlite3.Connection,
    result: SettlementCommitResult,
) -> None:
    deaths = _death_deltas(
        AdjudicationProposal(
            result_tier=result.facts.result_tier,
            deltas=result.facts.deltas,
        ),
    )
    record = _get_terminal_record(conn, result.facts.settlement_id)
    if deaths:
        if len(deaths) != 1 or record is None:
            raise WorldCorruptDataError("terminal action replay is missing its terminal record")
        if (
            record.version_id != result.version.version_id
            or record.previous_version_id != result.facts.parent_version_id
            or record.trigger_action != result.facts.client_action_id
        ):
            raise WorldCorruptDataError("terminal action replay identity is inconsistent")
    elif record is not None:
        raise WorldCorruptDataError("non-terminal action unexpectedly owns a terminal record")


def _validate_terminal_commit(
    *,
    intent: ActionIntent,
    previous_state: GameState,
    state: GameState,
    proposal: AdjudicationProposal,
    settlement_id: SettlementId,
    version_id: VersionId,
    terminal: bool,
) -> PlayerWorldDelta | None:
    if previous_state.player_world_status.life_status == "dead":
        raise WorldTerminalStateError()
    deaths = _death_deltas(proposal)
    if terminal:
        if len(deaths) != 1:
            raise WorldCorruptDataError("terminal commit requires exactly one death delta")
        death = deaths[0]
        player = state.player_world_status
        if (
            death.trigger_action != intent.client_action_id
            or death.before_value != "alive"
            or death.value != "dead"
            or not death.direct_cause
            or not death.key_factors
            or not death.causal_summary
            or player.life_status != "dead"
            or player.terminal_settlement_id != settlement_id
            or player.terminal_version_id != version_id
        ):
            raise WorldCorruptDataError("terminal commit state does not match its death delta")
        return death

    if deaths:
        raise WorldCorruptDataError("ordinary settlement cannot contain a death delta")
    before_player = previous_state.player_world_status
    after_player = state.player_world_status
    if (
        after_player.life_status != before_player.life_status
        or after_player.terminal_settlement_id != before_player.terminal_settlement_id
        or after_player.terminal_version_id != before_player.terminal_version_id
    ):
        raise WorldCorruptDataError("ordinary settlement cannot mutate terminal player state")
    return None


def _insert_terminal_record(
    conn: sqlite3.Connection,
    record: TerminalRecordFacts,
) -> None:
    conn.execute(
        """
        INSERT INTO terminal_records (
            id, game_id, branch_id, settlement_id, version_id,
            previous_version_id, facts_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(record.terminal_record_id),
            str(record.game_id),
            str(record.branch_id),
            str(record.settlement_id),
            str(record.version_id),
            str(record.previous_version_id),
            record.model_dump_json(),
            record.committed_at.isoformat(),
        ),
    )


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


def _append_unique_entity_id(result: list[EntityId], value: object) -> None:
    if isinstance(value, UUID) and value not in result:
        result.append(value)


def _settlement_prompt_targets(
    intent: ActionIntent,
    state: GameState,
    proposal: AdjudicationProposal,
) -> tuple[list[str], list[EntityId], list[EntityId]]:
    region_ids: list[EntityId] = []
    entity_ids: list[EntityId] = []

    _append_unique_entity_id(region_ids, intent.target_region_id)
    for entity_id in intent.target_entity_ids:
        target = state.entity_registry.get(entity_id)
        _append_unique_entity_id(
            region_ids if isinstance(target, RegionEntity) else entity_ids,
            entity_id,
        )

    for delta in proposal.deltas:
        scope = getattr(delta, "target_scope", None)
        target_id = getattr(delta, "target_id", None)
        if scope == "region":
            _append_unique_entity_id(region_ids, target_id)
        elif scope == "entity":
            _append_unique_entity_id(entity_ids, target_id)

        for field in (
            "target_entity_id",
            "from_entity_id",
            "to_entity_id",
            "office_entity_id",
            "holder_entity_id",
            "before_holder_entity_id",
        ):
            value = getattr(delta, field, None)
            target = state.entity_registry.get(value)
            _append_unique_entity_id(
                region_ids if isinstance(target, RegionEntity) else entity_ids,
                value,
            )
        for source in getattr(delta, "sources", ()):
            _append_unique_entity_id(entity_ids, getattr(source, "entity_id", None))
        for entity in getattr(delta, "result_entities", ()):
            _append_unique_entity_id(entity_ids, getattr(entity, "entity_id", None))

    regional_targets: list[str] = []
    for raw_name in intent.regional_targets:
        name = raw_name.strip()
        if name and name not in regional_targets:
            regional_targets.append(name)
    for entity_id in region_ids:
        entity = state.entity_registry.get(entity_id)
        if not isinstance(entity, RegionEntity):
            continue
        name = entity.legacy_name or entity.display_name
        if name in REGION_NAMES and name not in regional_targets:
            regional_targets.append(name)
    return regional_targets, region_ids, entity_ids


@coordinated_storage_write
def commit_settlement(
    intent: ActionIntent,
    state: GameState,
    proposal: AdjudicationProposal,
    *,
    time_plan: ElapsedSegmentPlan | None = None,
    executor_facts: ExecutorFacts | None = None,
    world_state_attribution: list[AppliedMetricAttribution] | None = None,
    rolls: list[RollRecord] | None = None,
    settlement_id: SettlementId | None = None,
    version_id: VersionId | None = None,
    activity_id: ActivityId | None = None,
    checkpoint_id: CheckpointId | None = None,
    checkpoint_sequence: int | None = None,
    activity_status: str | None = None,
    crossed_events: list[str] | None = None,
    actual_outcome: str | None = None,
    terminal: bool = False,
) -> SettlementCommitResult:
    """Commit one action request, settlement, snapshot, and head advance.

    The legal ``result_tier='failure'`` is committed like any other adjudicated
    result. Provider/schema failures never call this function. The branch head
    is checked again under ``BEGIN IMMEDIATE`` so stale proposals cannot land.
    """

    payload_hash = intent.payload_hash()
    settlement_id = settlement_id or new_settlement_id()
    version_id = version_id or new_version_id()
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
                _validate_terminal_replay(conn, result)
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
            death = _validate_terminal_commit(
                intent=intent,
                previous_state=previous_state,
                state=state,
                proposal=proposal,
                settlement_id=settlement_id,
                version_id=version_id,
                terminal=terminal,
            )

            _insert_action_request(conn, intent, payload_hash, committed_at)
            regional_targets, target_region_ids, target_entity_ids = (
                _settlement_prompt_targets(intent, state, proposal)
            )
            attribution = SettlementAttribution(
                requested_executor_id=proposal.requested_executor_id,
                actual_executor_id=proposal.actual_executor_id,
                execution_status=proposal.execution_status,
                provider=proposal.provider,
                executor_facts=executor_facts,
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
                regional_targets=regional_targets,
                target_region_ids=target_region_ids,
                target_entity_ids=target_entity_ids,
                deltas=proposal.deltas,
                duration_reason=proposal.duration_reason,
                time_plan=time_plan,
                activity_id=activity_id,
                checkpoint_id=checkpoint_id,
                checkpoint_sequence=checkpoint_sequence,
                activity_status=activity_status,
                crossed_events=list(crossed_events or ()),
                actual_outcome=actual_outcome,
                attribution=attribution,
                world_state_attribution=list(world_state_attribution or ()),
                rolls=list(rolls or ()),
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
            if death is not None:
                _insert_terminal_record(
                    conn,
                    TerminalRecordFacts(
                        terminal_record_id=new_terminal_record_id(),
                        game_id=intent.game_id,
                        branch_id=intent.branch_id,
                        settlement_id=settlement_id,
                        previous_version_id=intent.expected_parent_version_id,
                        version_id=version_id,
                        trigger_action=intent.client_action_id,
                        direct_cause=death.direct_cause or "",
                        key_factors=death.key_factors,
                        causal_summary=death.causal_summary or "",
                        committed_at=committed_at,
                    ),
                )
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


def commit_terminal_settlement(
    intent: ActionIntent,
    state: GameState,
    proposal: AdjudicationProposal,
    **kwargs,
) -> SettlementCommitResult:
    """Commit death facts, terminal record, snapshot, and head in one transaction."""

    return commit_settlement(
        intent,
        state,
        proposal,
        terminal=True,
        **kwargs,
    )


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
            permissions=[
                PermissionReference(
                    permission_id=new_permission_id(),
                    capability=capability,
                )
                for capability in (
                    ASSEMBLY_PARTICIPATE_CAPABILITY,
                    ENTITY_DIALOGUE_CAPABILITY,
                    MEMORIAL_SUBMIT_CAPABILITY,
                    OFFICE_APPOINTABLE_CAPABILITY,
                )
            ],
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


@coordinated_storage_write
def import_legacy_save(save_id: int) -> LegacyWorldImportResult:
    """Import one legacy row without updating or deleting it.

    The decoded copy is migrated in memory. The source bytes, migration notes,
    protected root graph, and idempotency ledger are committed together.
    """

    from .saves import _incompatible_year, _migrate_save

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
                if _incompatible_year(decoded):
                    raise LegacySaveIncompatibleError(save_id)
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


class WorldTerminalStateError(WorldStoreError):
    def __init__(self):
        super().__init__("world_terminal", "主角已死亡，当前世界线不能继续提交行动")


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


class LegacySaveIncompatibleError(WorldStoreError):
    def __init__(self, save_id: int):
        self.save_id = save_id
        super().__init__(
            "legacy_save_incompatible",
            f"Legacy save {save_id} belongs to an incompatible scenario",
        )
