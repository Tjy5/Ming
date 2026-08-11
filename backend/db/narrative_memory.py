"""Branch/version-scoped narrative memory and post-commit artifacts.

This repository is intentionally separate from the gameplay transaction owner
in :mod:`db.worlds`.  It may record or replace a display artifact after a world
settlement commits, but it can never advance a branch head or mutate a snapshot.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ai.narrative_context import NarrativeMemoryView
from ai.narrative_registry import NarrativePathId
from models.world import BranchId, EntityId, GameId, SettlementId, VersionId


MemoryKind = Literal[
    "raw_recent",
    "commitment",
    "relationship",
    "decision",
    "world_fact",
    "chapter_summary",
    "phase_summary",
]
MemoryRole = Literal["user", "assistant", "system"]
RetentionScope = Literal["recent", "chapter", "phase"]
NarrativeArtifactStatus = Literal[
    "validated",
    "repaired",
    "sanitized",
    "fallback_facts",
]


class NarrativeStoreError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class NarrativeStoreNotFoundError(NarrativeStoreError):
    def __init__(self, resource: str, identity: str):
        super().__init__("narrative_not_found", f"{resource} {identity} not found")


class NarrativeStoreConflictError(NarrativeStoreError):
    def __init__(self, message: str):
        super().__init__("narrative_conflict", message)


class NarrativeStorageError(NarrativeStoreError):
    def __init__(self):
        super().__init__("narrative_storage_error", "叙事记录失败，存储异常")


class _NarrativeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class NarrativeMemoryRecord(_NarrativeRecord):
    memory_id: UUID
    game_id: GameId
    branch_id: BranchId
    source_version_id: VersionId
    source_settlement_id: SettlementId | None = None
    mode: str = Field(min_length=1, max_length=120)
    phase: str = Field(min_length=1, max_length=120)
    chapter: str = Field(min_length=1, max_length=120)
    person_entity_id: EntityId | None = None
    topic_id: str = Field(min_length=1, max_length=240)
    kind: MemoryKind
    role: MemoryRole
    content: str = Field(min_length=1, max_length=12000)
    created_world_hour: int = Field(strict=True, ge=0)
    source_memory_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def _validate_summary_sources(self) -> "NarrativeMemoryRecord":
        is_summary = self.kind in {"chapter_summary", "phase_summary"}
        if is_summary and not self.source_memory_ids:
            raise ValueError("boundary summary requires source memory ids")
        if not is_summary and self.source_memory_ids:
            raise ValueError("only boundary summaries may reference source memories")
        if len(set(self.source_memory_ids)) != len(self.source_memory_ids):
            raise ValueError("summary source memory ids must be unique")
        return self

    def to_context_view(self) -> NarrativeMemoryView:
        return NarrativeMemoryView(
            memory_id=self.memory_id,
            source_version_id=self.source_version_id,
            source_branch_id=self.branch_id,
            mode=self.mode,
            phase=self.phase,
            chapter=self.chapter,
            person_entity_id=self.person_entity_id,
            topic_id=self.topic_id,
            kind=self.kind,
            role=self.role,
            content=self.content,
            created_world_hour=self.created_world_hour,
            created_at=self.created_at,
        )


class NarrativeArtifactRecord(_NarrativeRecord):
    artifact_id: UUID
    game_id: GameId
    branch_id: BranchId
    settlement_id: SettlementId
    context_version_id: VersionId
    path_id: NarrativePathId
    status: NarrativeArtifactStatus
    text: str = Field(min_length=1, max_length=50000)
    finding_codes: list[str] = Field(default_factory=list)
    attempt_count: int = Field(strict=True, ge=1, le=2)
    provider_label: str | None = Field(default=None, max_length=120)
    model_label: str | None = Field(default=None, max_length=240)
    request_id: str | None = Field(default=None, max_length=240)
    context_schema_version: str = Field(default="narrative-context-v1", min_length=1)
    source_versions: dict[str, str] = Field(default_factory=dict)
    outcome_stage: NarrativeArtifactStatus = "validated"
    duration_ms: int = Field(default=0, strict=True, ge=0)
    created_at: datetime


def _connect() -> sqlite3.Connection:
    from . import saves

    return saves._connect()


def init_narrative_memory_db() -> None:
    with closing(_connect()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS narrative_memories (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                source_version_id TEXT NOT NULL,
                source_settlement_id TEXT,
                mode TEXT NOT NULL,
                phase TEXT NOT NULL,
                chapter TEXT NOT NULL,
                person_entity_id TEXT,
                topic_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN (
                    'raw_recent', 'commitment', 'relationship', 'decision',
                    'world_fact', 'chapter_summary', 'phase_summary'
                )),
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                created_world_hour INTEGER NOT NULL CHECK (created_world_hour >= 0),
                source_memory_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (game_id, branch_id)
                    REFERENCES branches(game_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, source_version_id)
                    REFERENCES versions(game_id, branch_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, source_settlement_id)
                    REFERENCES settlements(game_id, branch_id, id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS narrative_artifacts (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                context_version_id TEXT NOT NULL,
                path_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN (
                    'validated', 'repaired', 'sanitized', 'fallback_facts'
                )),
                text TEXT NOT NULL,
                finding_codes_json TEXT NOT NULL,
                attempt_count INTEGER NOT NULL CHECK (attempt_count BETWEEN 1 AND 2),
                provider_label TEXT,
                model_label TEXT,
                request_id TEXT,
                context_schema_version TEXT NOT NULL DEFAULT 'narrative-context-v1',
                source_versions_json TEXT NOT NULL DEFAULT '{}',
                outcome_stage TEXT NOT NULL DEFAULT 'validated',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE (game_id, branch_id, settlement_id, path_id, id),
                FOREIGN KEY (game_id, branch_id)
                    REFERENCES branches(game_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, settlement_id)
                    REFERENCES settlements(game_id, branch_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, context_version_id)
                    REFERENCES versions(game_id, branch_id, id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS narrative_memory_sources (
                summary_memory_id TEXT NOT NULL,
                source_memory_id TEXT NOT NULL,
                PRIMARY KEY (summary_memory_id, source_memory_id),
                FOREIGN KEY (summary_memory_id)
                    REFERENCES narrative_memories(id) ON DELETE RESTRICT,
                FOREIGN KEY (source_memory_id)
                    REFERENCES narrative_memories(id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS narrative_current_display (
                game_id TEXT NOT NULL,
                branch_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                path_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL UNIQUE,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (game_id, branch_id, settlement_id, path_id),
                FOREIGN KEY (game_id, branch_id, settlement_id)
                    REFERENCES settlements(game_id, branch_id, id) ON DELETE RESTRICT,
                FOREIGN KEY (artifact_id)
                    REFERENCES narrative_artifacts(id) ON DELETE RESTRICT,
                FOREIGN KEY (game_id, branch_id, settlement_id, path_id, artifact_id)
                    REFERENCES narrative_artifacts(
                        game_id, branch_id, settlement_id, path_id, id
                    ) ON DELETE RESTRICT
            );

            CREATE TRIGGER IF NOT EXISTS trg_narrative_artifact_context_version
            BEFORE INSERT ON narrative_artifacts
            WHEN NOT EXISTS (
                SELECT 1 FROM versions
                WHERE versions.game_id = NEW.game_id
                  AND versions.branch_id = NEW.branch_id
                  AND versions.id = NEW.context_version_id
                  AND versions.settlement_id = NEW.settlement_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'artifact context must be the settlement result version');
            END;

            CREATE INDEX IF NOT EXISTS idx_narrative_memory_scope
                ON narrative_memories (
                    game_id, mode, phase, chapter, topic_id, person_entity_id,
                    created_world_hour, created_at, id
                );
            CREATE INDEX IF NOT EXISTS idx_narrative_memory_version
                ON narrative_memories (game_id, source_version_id);
            CREATE INDEX IF NOT EXISTS idx_narrative_memory_source
                ON narrative_memory_sources (source_memory_id, summary_memory_id);
            CREATE INDEX IF NOT EXISTS idx_narrative_artifact_settlement
                ON narrative_artifacts (
                    game_id, branch_id, settlement_id, created_at, id
                );
            """,
        )
        # Legacy artifact tables predate the path-scoped display foreign key.
        # A unique index is sufficient as the SQLite parent key and avoids a
        # destructive artifact-table rebuild for existing saves.
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_narrative_artifact_scope_path_id
            ON narrative_artifacts (
                game_id, branch_id, settlement_id, path_id, id
            )
            """,
        )
        _migrate_artifact_diagnostics(conn)
        _migrate_current_display_path_scope(conn)
        conn.commit()


def _migrate_artifact_diagnostics(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(narrative_artifacts)").fetchall()
    }
    additions = (
        (
            "context_schema_version",
            "TEXT NOT NULL DEFAULT 'narrative-context-v1'",
        ),
        ("source_versions_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("outcome_stage", "TEXT NOT NULL DEFAULT 'validated'"),
        ("duration_ms", "INTEGER NOT NULL DEFAULT 0"),
    )
    for name, declaration in additions:
        if name not in columns:
            conn.execute(
                f"ALTER TABLE narrative_artifacts ADD COLUMN {name} {declaration}",
            )
    conn.execute("UPDATE narrative_artifacts SET outcome_stage = status")


def _migrate_current_display_path_scope(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(narrative_current_display)").fetchall()
    }
    legacy_exists = conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'narrative_current_display_legacy'
        """,
    ).fetchone() is not None
    if not columns:
        return
    if "path_id" in columns:
        # Recover cleanly if an earlier process was interrupted after the
        # legacy table rename but before copying its rows.
        if legacy_exists:
            conn.executescript(
                """
                INSERT OR IGNORE INTO narrative_current_display (
                    game_id, branch_id, settlement_id, path_id, artifact_id, updated_at
                )
                SELECT legacy.game_id, legacy.branch_id, legacy.settlement_id,
                       artifacts.path_id, legacy.artifact_id, legacy.updated_at
                FROM narrative_current_display_legacy AS legacy
                JOIN narrative_artifacts AS artifacts ON artifacts.id = legacy.artifact_id;
                DROP TABLE narrative_current_display_legacy;
                """,
            )
        return
    conn.executescript(
        """
        ALTER TABLE narrative_current_display RENAME TO narrative_current_display_legacy;
        CREATE TABLE narrative_current_display (
            game_id TEXT NOT NULL,
            branch_id TEXT NOT NULL,
            settlement_id TEXT NOT NULL,
            path_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL UNIQUE,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (game_id, branch_id, settlement_id, path_id),
            FOREIGN KEY (game_id, branch_id, settlement_id)
                REFERENCES settlements(game_id, branch_id, id) ON DELETE RESTRICT,
            FOREIGN KEY (artifact_id)
                REFERENCES narrative_artifacts(id) ON DELETE RESTRICT,
            FOREIGN KEY (game_id, branch_id, settlement_id, path_id, artifact_id)
                REFERENCES narrative_artifacts(
                    game_id, branch_id, settlement_id, path_id, id
                ) ON DELETE RESTRICT
        );
        INSERT INTO narrative_current_display (
            game_id, branch_id, settlement_id, path_id, artifact_id, updated_at
        )
        SELECT legacy.game_id, legacy.branch_id, legacy.settlement_id,
               artifacts.path_id, legacy.artifact_id, legacy.updated_at
        FROM narrative_current_display_legacy AS legacy
        JOIN narrative_artifacts AS artifacts ON artifacts.id = legacy.artifact_id;
        DROP TABLE narrative_current_display_legacy;
        """,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_memory(row: sqlite3.Row) -> NarrativeMemoryRecord:
    return NarrativeMemoryRecord.model_validate(
        {
            "memory_id": row["id"],
            "game_id": row["game_id"],
            "branch_id": row["branch_id"],
            "source_version_id": row["source_version_id"],
            "source_settlement_id": row["source_settlement_id"],
            "mode": row["mode"],
            "phase": row["phase"],
            "chapter": row["chapter"],
            "person_entity_id": row["person_entity_id"],
            "topic_id": row["topic_id"],
            "kind": row["kind"],
            "role": row["role"],
            "content": row["content"],
            "created_world_hour": row["created_world_hour"],
            "source_memory_ids": json.loads(row["source_memory_ids_json"]),
            "created_at": row["created_at"],
        },
    )


def append_memory(
    *,
    game_id: GameId,
    branch_id: BranchId,
    source_version_id: VersionId,
    mode: str,
    phase: str,
    chapter: str,
    topic_id: str,
    kind: MemoryKind,
    role: MemoryRole,
    content: str,
    created_world_hour: int,
    source_settlement_id: SettlementId | None = None,
    person_entity_id: EntityId | None = None,
    source_memory_ids: list[UUID] | None = None,
    memory_id: UUID | None = None,
    created_at: datetime | None = None,
) -> NarrativeMemoryRecord:
    record = NarrativeMemoryRecord(
        memory_id=memory_id or uuid4(),
        game_id=game_id,
        branch_id=branch_id,
        source_version_id=source_version_id,
        source_settlement_id=source_settlement_id,
        mode=mode.strip(),
        phase=phase.strip(),
        chapter=chapter.strip(),
        person_entity_id=person_entity_id,
        topic_id=topic_id.strip(),
        kind=kind,
        role=role,
        content=content.strip(),
        created_world_hour=created_world_hour,
        source_memory_ids=list(source_memory_ids or []),
        created_at=created_at or _utc_now(),
    )
    payload = (
        str(record.memory_id),
        str(record.game_id),
        str(record.branch_id),
        str(record.source_version_id),
        str(record.source_settlement_id) if record.source_settlement_id else None,
        record.mode,
        record.phase,
        record.chapter,
        str(record.person_entity_id) if record.person_entity_id else None,
        record.topic_id,
        record.kind,
        record.role,
        record.content,
        record.created_world_hour,
        json.dumps([str(item) for item in record.source_memory_ids]),
        record.created_at.isoformat(),
    )
    try:
        with closing(_connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM narrative_memories WHERE id = ?",
                (str(record.memory_id),),
            ).fetchone()
            if existing is not None:
                current = _row_to_memory(existing)
                if current.model_dump(exclude={"created_at"}) == record.model_dump(
                    exclude={"created_at"},
                ):
                    conn.commit()
                    return current
                raise NarrativeStoreConflictError(
                    "memory id was already used for different content",
                )
            if record.source_memory_ids:
                _validate_summary_sources_conn(
                    conn,
                    source_memory_ids=record.source_memory_ids,
                    game_id=record.game_id,
                    branch_id=record.branch_id,
                    source_version_id=record.source_version_id,
                    mode=record.mode,
                    topic_id=record.topic_id,
                    person_entity_id=record.person_entity_id,
                )
            conn.execute(
                """
                INSERT INTO narrative_memories (
                    id, game_id, branch_id, source_version_id,
                    source_settlement_id, mode, phase, chapter,
                    person_entity_id, topic_id,
                    kind, role, content, created_world_hour,
                    source_memory_ids_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            if record.source_memory_ids:
                conn.executemany(
                    """
                    INSERT INTO narrative_memory_sources (
                        summary_memory_id, source_memory_id
                    ) VALUES (?, ?)
                    """,
                    [
                        (str(record.memory_id), str(source_id))
                        for source_id in record.source_memory_ids
                    ],
                )
            conn.commit()
        return record
    except NarrativeStoreError:
        raise
    except sqlite3.IntegrityError as exc:
        # A concurrent retry with the same stable id may have won between the
        # SELECT and INSERT.  Replay it only when every caller-owned field is
        # identical; otherwise preserve the conflict.
        try:
            with closing(_connect()) as conn:
                existing = conn.execute(
                    "SELECT * FROM narrative_memories WHERE id = ?",
                    (str(record.memory_id),),
                ).fetchone()
            if existing is not None:
                current = _row_to_memory(existing)
                if current.model_dump(exclude={"created_at"}) == record.model_dump(
                    exclude={"created_at"},
                ):
                    return current
        except (sqlite3.Error, ValidationError, ValueError, TypeError, json.JSONDecodeError):
            pass
        raise NarrativeStoreConflictError(
            "memory scope does not reference one committed game/branch/version",
        ) from exc
    except sqlite3.Error as exc:
        raise NarrativeStorageError() from exc


_KINDS_BY_RETENTION: dict[RetentionScope, tuple[MemoryKind, ...]] = {
    "recent": (
        "raw_recent",
        "commitment",
        "relationship",
        "decision",
        "world_fact",
        "chapter_summary",
        "phase_summary",
    ),
    "chapter": ("commitment", "chapter_summary"),
    "phase": ("relationship", "decision", "world_fact", "phase_summary"),
}


def list_visible_memories(
    *,
    game_id: GameId,
    branch_id: BranchId,
    version_id: VersionId,
    mode: str,
    topic_id: str,
    person_entity_id: EntityId | None = None,
    retention_scope: RetentionScope = "recent",
    current_phase: str | None = None,
    current_chapter: str | None = None,
    limit: int = 20,
) -> list[NarrativeMemoryRecord]:
    if limit < 1 or limit > 200:
        raise ValueError("memory limit must be between 1 and 200")
    kinds = _KINDS_BY_RETENTION[retention_scope]
    placeholders = ", ".join("?" for _ in kinds)
    person_value = str(person_entity_id) if person_entity_id else None
    if (current_phase is None) != (current_chapter is None):
        raise ValueError("current phase and chapter must be supplied together")
    if current_phase is None:
        retention_sql = f"AND memories.kind IN ({placeholders})"
        retention_params: tuple[object, ...] = tuple(kinds)
    else:
        retention_sql = """
                  AND (
                      (memories.phase = ? AND memories.chapter = ?)
                      OR (
                          memories.phase = ? AND memories.chapter <> ?
                          AND memories.kind IN ('commitment', 'chapter_summary')
                      )
                      OR (
                          memories.phase <> ?
                          AND memories.kind IN (
                              'relationship', 'decision', 'world_fact', 'phase_summary'
                          )
                      )
                  )
        """
        retention_params = (
            current_phase, current_chapter,
            current_phase, current_chapter,
            current_phase,
        )
    try:
        with closing(_connect()) as conn:
            current = conn.execute(
                "SELECT game_id, branch_id FROM versions WHERE id = ?",
                (str(version_id),),
            ).fetchone()
            if (
                current is None
                or current["game_id"] != str(game_id)
                or current["branch_id"] != str(branch_id)
            ):
                raise NarrativeStoreNotFoundError("version", str(version_id))
            rows = conn.execute(
                f"""
                WITH RECURSIVE ancestry(id, depth) AS (
                    SELECT id, 0 FROM versions WHERE id = ? AND game_id = ?
                    UNION ALL
                    SELECT versions.parent_version_id, ancestry.depth + 1
                    FROM versions
                    JOIN ancestry ON versions.id = ancestry.id
                    WHERE versions.game_id = ?
                      AND versions.parent_version_id IS NOT NULL
                )
                SELECT memories.*
                FROM narrative_memories AS memories
                JOIN ancestry ON ancestry.id = memories.source_version_id
                WHERE memories.game_id = ?
                  AND memories.mode = ?
                  AND memories.topic_id = ?
                  AND (
                      memories.person_entity_id = ?
                      OR (memories.person_entity_id IS NULL AND ? IS NULL)
                  )
                  {retention_sql}
                ORDER BY memories.created_world_hour DESC,
                         memories.created_at DESC,
                         memories.id DESC
                LIMIT ?
                """,
                (
                    str(version_id),
                    str(game_id),
                    str(game_id),
                    str(game_id),
                    mode.strip(),
                    topic_id.strip(),
                    person_value,
                    person_value,
                    *retention_params,
                    limit,
                ),
            ).fetchall()
        records = [_row_to_memory(row) for row in rows]
        records.reverse()
        return records
    except NarrativeStoreError:
        raise
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise NarrativeStoreConflictError("stored narrative memory is invalid") from exc
    except sqlite3.Error as exc:
        raise NarrativeStorageError() from exc


def append_boundary_summary(
    *,
    scope: Literal["chapter", "phase"],
    content: str,
    source_memory_ids: list[UUID],
    game_id: GameId,
    branch_id: BranchId,
    source_version_id: VersionId,
    mode: str,
    phase: str,
    chapter: str,
    topic_id: str,
    created_world_hour: int,
    person_entity_id: EntityId | None = None,
    memory_id: UUID | None = None,
) -> NarrativeMemoryRecord:
    if not source_memory_ids:
        raise ValueError("boundary summary requires source memory ids")
    return append_memory(
        game_id=game_id,
        branch_id=branch_id,
        source_version_id=source_version_id,
        mode=mode,
        phase=phase,
        chapter=chapter,
        topic_id=topic_id,
        kind="chapter_summary" if scope == "chapter" else "phase_summary",
        role="system",
        content=content,
        created_world_hour=created_world_hour,
        person_entity_id=person_entity_id,
        source_memory_ids=source_memory_ids,
        memory_id=memory_id,
    )


def _validate_summary_sources(
    *,
    source_memory_ids: list[UUID],
    game_id: GameId,
    branch_id: BranchId,
    source_version_id: VersionId,
    mode: str,
    phase: str,
    chapter: str,
    topic_id: str,
    person_entity_id: EntityId | None,
) -> None:
    del phase, chapter  # summaries may intentionally consume the previous boundary
    try:
        with closing(_connect()) as conn:
            _validate_summary_sources_conn(
                conn,
                source_memory_ids=source_memory_ids,
                game_id=game_id,
                branch_id=branch_id,
                source_version_id=source_version_id,
                mode=mode,
                topic_id=topic_id,
                person_entity_id=person_entity_id,
            )
    except NarrativeStoreError:
        raise
    except sqlite3.Error as exc:
        raise NarrativeStorageError() from exc


def _validate_summary_sources_conn(
    conn: sqlite3.Connection,
    *,
    source_memory_ids: list[UUID],
    game_id: GameId,
    branch_id: BranchId,
    source_version_id: VersionId,
    mode: str,
    topic_id: str,
    person_entity_id: EntityId | None,
) -> None:
    if len(set(source_memory_ids)) != len(source_memory_ids):
        raise NarrativeStoreConflictError("summary source memory ids must be unique")
    placeholders = ", ".join("?" for _ in source_memory_ids)
    person_value = str(person_entity_id) if person_entity_id else None
    current = conn.execute(
        "SELECT game_id, branch_id FROM versions WHERE id = ?",
        (str(source_version_id),),
    ).fetchone()
    if (
        current is None
        or current["game_id"] != str(game_id)
        or current["branch_id"] != str(branch_id)
    ):
        raise NarrativeStoreNotFoundError("version", str(source_version_id))
    rows = conn.execute(
        f"""
                WITH RECURSIVE ancestry(id) AS (
                    SELECT id FROM versions WHERE id = ? AND game_id = ?
                    UNION ALL
                    SELECT versions.parent_version_id
                    FROM versions
                    JOIN ancestry ON versions.id = ancestry.id
                    WHERE versions.game_id = ?
                      AND versions.parent_version_id IS NOT NULL
                )
                SELECT memories.id
                FROM narrative_memories AS memories
                JOIN ancestry ON ancestry.id = memories.source_version_id
                WHERE memories.game_id = ?
                  AND memories.mode = ?
                  AND memories.topic_id = ?
                  AND (
                      memories.person_entity_id = ?
                      OR (memories.person_entity_id IS NULL AND ? IS NULL)
                  )
                  AND memories.id IN ({placeholders})
        """,
        (
            str(source_version_id), str(game_id), str(game_id), str(game_id),
            mode.strip(), topic_id.strip(), person_value, person_value,
            *(str(item) for item in source_memory_ids),
        ),
    ).fetchall()
    visible_ids = {UUID(row["id"]) for row in rows}
    if visible_ids != set(source_memory_ids):
        raise NarrativeStoreConflictError(
            "summary sources must be visible ancestors in the same memory scope",
        )


def _row_to_artifact(row: sqlite3.Row) -> NarrativeArtifactRecord:
    return NarrativeArtifactRecord.model_validate(
        {
            "artifact_id": row["id"],
            "game_id": row["game_id"],
            "branch_id": row["branch_id"],
            "settlement_id": row["settlement_id"],
            "context_version_id": row["context_version_id"],
            "path_id": row["path_id"],
            "status": row["status"],
            "text": row["text"],
            "finding_codes": json.loads(row["finding_codes_json"]),
            "attempt_count": row["attempt_count"],
            "provider_label": row["provider_label"],
            "model_label": row["model_label"],
            "request_id": row["request_id"],
            "context_schema_version": row["context_schema_version"],
            "source_versions": json.loads(row["source_versions_json"]),
            "outcome_stage": row["outcome_stage"],
            "duration_ms": row["duration_ms"],
            "created_at": row["created_at"],
        },
    )


def save_artifact(
    *,
    game_id: GameId,
    branch_id: BranchId,
    settlement_id: SettlementId,
    context_version_id: VersionId,
    path_id: NarrativePathId,
    status: NarrativeArtifactStatus,
    text: str,
    finding_codes: list[str] | None = None,
    attempt_count: int = 1,
    provider_label: str | None = None,
    model_label: str | None = None,
    request_id: str | None = None,
    context_schema_version: str = "narrative-context-v1",
    source_versions: dict[str, str] | None = None,
    outcome_stage: NarrativeArtifactStatus | None = None,
    duration_ms: int = 0,
    artifact_id: UUID | None = None,
    make_current: bool = True,
) -> NarrativeArtifactRecord:
    record = NarrativeArtifactRecord(
        artifact_id=artifact_id or uuid4(),
        game_id=game_id,
        branch_id=branch_id,
        settlement_id=settlement_id,
        context_version_id=context_version_id,
        path_id=path_id,
        status=status,
        text=text.strip(),
        finding_codes=sorted(set(finding_codes or [])),
        attempt_count=attempt_count,
        provider_label=provider_label,
        model_label=model_label,
        request_id=request_id,
        context_schema_version=context_schema_version,
        source_versions=dict(source_versions or {}),
        outcome_stage=outcome_stage or status,
        duration_ms=duration_ms,
        created_at=_utc_now(),
    )
    try:
        with closing(_connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM narrative_artifacts WHERE id = ?",
                (str(record.artifact_id),),
            ).fetchone()
            if existing is not None:
                current = _row_to_artifact(existing)
                if current.model_dump(exclude={"created_at"}) != record.model_dump(
                    exclude={"created_at"},
                ):
                    raise NarrativeStoreConflictError(
                        "artifact id was already used for different content",
                    )
                if make_current:
                    conn.execute(
                        """
                        INSERT INTO narrative_current_display (
                            game_id, branch_id, settlement_id, path_id, artifact_id, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(game_id, branch_id, settlement_id, path_id) DO UPDATE SET
                            artifact_id = excluded.artifact_id,
                            updated_at = excluded.updated_at
                        """,
                        (
                            str(current.game_id), str(current.branch_id),
                            str(current.settlement_id), current.path_id,
                            str(current.artifact_id),
                            _utc_now().isoformat(),
                        ),
                    )
                conn.commit()
                return current
            conn.execute(
                """
                INSERT INTO narrative_artifacts (
                    id, game_id, branch_id, settlement_id, context_version_id,
                    path_id, status, text, finding_codes_json, attempt_count,
                    provider_label, model_label, request_id,
                    context_schema_version, source_versions_json,
                    outcome_stage, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.artifact_id), str(record.game_id), str(record.branch_id),
                    str(record.settlement_id), str(record.context_version_id), record.path_id,
                    record.status, record.text, json.dumps(record.finding_codes),
                    record.attempt_count, record.provider_label, record.model_label,
                    record.request_id, record.context_schema_version,
                    json.dumps(record.source_versions, sort_keys=True),
                    record.outcome_stage, record.duration_ms,
                    record.created_at.isoformat(),
                ),
            )
            if make_current:
                conn.execute(
                    """
                    INSERT INTO narrative_current_display (
                        game_id, branch_id, settlement_id, path_id, artifact_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(game_id, branch_id, settlement_id, path_id) DO UPDATE SET
                        artifact_id = excluded.artifact_id,
                        updated_at = excluded.updated_at
                    """,
                    (
                        str(record.game_id), str(record.branch_id),
                        str(record.settlement_id), record.path_id,
                        str(record.artifact_id),
                        record.created_at.isoformat(),
                    ),
                )
            conn.commit()
        return record
    except NarrativeStoreError:
        raise
    except sqlite3.IntegrityError as exc:
        try:
            with closing(_connect()) as conn:
                existing = conn.execute(
                    "SELECT * FROM narrative_artifacts WHERE id = ?",
                    (str(record.artifact_id),),
                ).fetchone()
            if existing is not None:
                current = _row_to_artifact(existing)
                if current.model_dump(exclude={"created_at"}) == record.model_dump(
                    exclude={"created_at"},
                ):
                    return current
        except (sqlite3.Error, ValidationError, ValueError, TypeError, json.JSONDecodeError):
            pass
        raise NarrativeStoreConflictError(
            "artifact scope does not match one committed settlement/version",
        ) from exc
    except sqlite3.Error as exc:
        raise NarrativeStorageError() from exc


def get_current_artifact(
    game_id: GameId,
    branch_id: BranchId,
    settlement_id: SettlementId,
    path_id: NarrativePathId,
) -> NarrativeArtifactRecord | None:
    try:
        with closing(_connect()) as conn:
            row = conn.execute(
                """
                SELECT artifacts.*
                FROM narrative_current_display AS display
                JOIN narrative_artifacts AS artifacts ON artifacts.id = display.artifact_id
                WHERE display.game_id = ? AND display.branch_id = ?
                  AND display.settlement_id = ? AND display.path_id = ?
                """,
                (str(game_id), str(branch_id), str(settlement_id), path_id),
            ).fetchone()
        return _row_to_artifact(row) if row is not None else None
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise NarrativeStoreConflictError("stored narrative artifact is invalid") from exc
    except sqlite3.Error as exc:
        raise NarrativeStorageError() from exc


def list_artifacts(
    game_id: GameId,
    branch_id: BranchId,
    settlement_id: SettlementId,
) -> list[NarrativeArtifactRecord]:
    try:
        with closing(_connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM narrative_artifacts
                WHERE game_id = ? AND branch_id = ? AND settlement_id = ?
                ORDER BY created_at, id
                """,
                (str(game_id), str(branch_id), str(settlement_id)),
            ).fetchall()
        return [_row_to_artifact(row) for row in rows]
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise NarrativeStoreConflictError("stored narrative artifact is invalid") from exc
    except sqlite3.Error as exc:
        raise NarrativeStorageError() from exc
