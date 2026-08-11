from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest

from ai.narrative_context import build_persisted_narrative_context
from db import narrative_memory, saves, worlds
from engine.calendar import advance_game_time
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal
from models.world import Duration, new_client_action_id


def _store(monkeypatch, tmp_path):
    db_path = tmp_path / "narrative-memory.db"
    monkeypatch.setattr(saves, "DB_PATH", db_path)
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    return db_path, root


def _commit(root, *, text="推进世界"):
    parent = worlds.load_version(root.version_id).state
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text=text,
        action_kind="decree",
    )
    proposal = AdjudicationProposal(
        result_tier="success",
        key_factors=["当前世界事实"],
        execution_status="completed",
    )
    return worlds.commit_settlement(intent, parent, proposal)


def _append(
    ref,
    *,
    content,
    kind="raw_recent",
    topic="same-topic",
    mode="chat",
    person_entity_id=None,
    memory_id=None,
):
    state = worlds.load_version(ref.version_id).state
    assert state.time.clock is not None
    return narrative_memory.append_memory(
        game_id=ref.game_id,
        branch_id=ref.branch_id,
        source_version_id=ref.version_id,
        source_settlement_id=ref.settlement_id,
        mode=mode,
        phase=state.phase,
        chapter=state.chapter,
        topic_id=topic,
        person_entity_id=person_entity_id,
        kind=kind,
        role="assistant",
        content=content,
        created_world_hour=state.time.clock.absolute_hour,
        memory_id=memory_id,
    )


def test_schema_initializes_memory_artifact_tables_and_indexes(monkeypatch, tmp_path):
    db_path, _root = _store(monkeypatch, tmp_path)
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'",
            )
        }
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'",
            )
        }
        artifact_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(narrative_artifacts)")
        }
    assert {
        "narrative_memories",
        "narrative_memory_sources",
        "narrative_artifacts",
        "narrative_current_display",
    } <= tables
    assert {
        "idx_narrative_memory_scope",
        "idx_narrative_memory_version",
        "idx_narrative_memory_source",
        "idx_narrative_artifact_settlement",
    } <= indexes
    assert {
        "context_schema_version",
        "source_versions_json",
        "outcome_stage",
        "duration_ms",
    } <= artifact_columns


def test_memory_visibility_follows_version_ancestry_not_process_or_name(
    monkeypatch,
    tmp_path,
):
    _db_path, root = _store(monkeypatch, tmp_path)
    root_memory = _append(root, content="共同祖先记忆")
    committed = _commit(root)
    branch_memory = _append(committed.version, content="分叉前记忆")
    fork = worlds.create_branch_from_version(committed.version.version_id)

    inherited = narrative_memory.list_visible_memories(
        game_id=fork.game_id,
        branch_id=fork.branch_id,
        version_id=fork.version_id,
        mode="chat",
        topic_id="same-topic",
    )
    assert [item.memory_id for item in inherited] == [
        root_memory.memory_id,
        branch_memory.memory_id,
    ]

    child_memory = _append(fork, content="只属于子分支")
    original = narrative_memory.list_visible_memories(
        game_id=committed.version.game_id,
        branch_id=committed.version.branch_id,
        version_id=committed.version.version_id,
        mode="chat",
        topic_id="same-topic",
    )
    assert child_memory.memory_id not in {item.memory_id for item in original}


def test_memory_retry_is_idempotent_and_changed_payload_conflicts(monkeypatch, tmp_path):
    _db_path, root = _store(monkeypatch, tmp_path)
    memory_id = uuid4()
    first = _append(root, content="稳定内容", memory_id=memory_id)
    replay = _append(root, content="稳定内容", memory_id=memory_id)
    assert replay == first
    with pytest.raises(narrative_memory.NarrativeStoreConflictError):
        _append(root, content="篡改内容", memory_id=memory_id)


def test_chapter_and_phase_views_exclude_raw_cross_boundary_text(monkeypatch, tmp_path):
    _db_path, root = _store(monkeypatch, tmp_path)
    raw = _append(root, content="原始跑团全文")
    _append(root, content="必须守诺", kind="commitment")
    _append(root, content="人物关系", kind="relationship")
    _append(root, content="玩家决定", kind="decision")
    _append(root, content="已生效事实", kind="world_fact")
    narrative_memory.append_boundary_summary(
        scope="chapter",
        content="篇章摘要",
        source_memory_ids=[raw.memory_id],
        game_id=root.game_id,
        branch_id=root.branch_id,
        source_version_id=root.version_id,
        mode="chat",
        phase="governance",
        chapter="chapter-b",
        topic_id="same-topic",
        created_world_hour=raw.created_world_hour,
    )
    narrative_memory.append_boundary_summary(
        scope="phase",
        content="阶段事实摘要",
        source_memory_ids=[raw.memory_id],
        game_id=root.game_id,
        branch_id=root.branch_id,
        source_version_id=root.version_id,
        mode="chat",
        phase="governance",
        chapter="chapter-b",
        topic_id="same-topic",
        created_world_hour=raw.created_world_hour,
    )

    chapter = narrative_memory.list_visible_memories(
        game_id=root.game_id,
        branch_id=root.branch_id,
        version_id=root.version_id,
        mode="chat",
        topic_id="same-topic",
        retention_scope="chapter",
    )
    phase = narrative_memory.list_visible_memories(
        game_id=root.game_id,
        branch_id=root.branch_id,
        version_id=root.version_id,
        mode="chat",
        topic_id="same-topic",
        retention_scope="phase",
    )
    assert {item.kind for item in chapter} == {"commitment", "chapter_summary"}
    assert {item.kind for item in phase} == {
        "relationship", "decision", "world_fact", "phase_summary",
    }
    assert all(item.memory_id != raw.memory_id for item in [*chapter, *phase])
    with saves._connect() as conn:
        links = conn.execute(
            "SELECT summary_memory_id, source_memory_id FROM narrative_memory_sources",
        ).fetchall()
    assert len(links) == 2
    assert {row["source_memory_id"] for row in links} == {str(raw.memory_id)}


def test_persisted_chat_context_keeps_same_topic_across_month_and_filters_scope(
    monkeypatch,
    tmp_path,
):
    _db_path, root = _store(monkeypatch, tmp_path)
    root_state = worlds.load_version(root.version_id).state
    person_id = root_state.player_world_status.player_character_id
    assert person_id is not None
    _append(root, content="同主题跨月祖先记忆", topic="river-plan")
    _append(root, content="其他主题污染", topic="grain-plan")
    _append(root, content="其他模式污染", topic="river-plan", mode="trpg")
    _append(
        root,
        content="人物私有污染",
        topic="river-plan",
        person_entity_id=person_id,
    )

    advanced = root_state.model_copy(deep=True)
    advance_game_time(advanced.time, Duration(unit="month", value=1))
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="跨月后继续同一议题",
        action_kind="decree",
    )
    result = worlds.commit_settlement(
        intent,
        advanced,
        AdjudicationProposal(
            result_tier="success",
            key_factors=["世界时钟已跨月"],
            execution_status="completed",
        ),
    )
    _append(result.version, content="跨月后的同主题记忆", topic="river-plan")
    current = worlds.load_version(result.version.version_id).state

    context = build_persisted_narrative_context(
        path_id="ordinary_chat",
        state=current,
        topic_id="river-plan",
        action_text="继续议论河防",
    )

    assert [memory.content for memory in context.memories] == [
        "同主题跨月祖先记忆",
        "跨月后的同主题记忆",
    ]
    assert context.time.absolute_hour > root_state.time.clock.absolute_hour


def test_artifact_display_updates_without_creating_world_versions(monkeypatch, tmp_path):
    _db_path, root = _store(monkeypatch, tmp_path)
    result = _commit(root)
    before_versions = worlds.list_versions(root.game_id, root.branch_id)
    first = narrative_memory.save_artifact(
        game_id=root.game_id,
        branch_id=root.branch_id,
        settlement_id=result.facts.settlement_id,
        context_version_id=result.facts.result_version_id,
        path_id="structured_action",
        status="fallback_facts",
        text="事实摘要",
    )
    second = narrative_memory.save_artifact(
        game_id=root.game_id,
        branch_id=root.branch_id,
        settlement_id=result.facts.settlement_id,
        context_version_id=result.facts.result_version_id,
        path_id="structured_action",
        status="validated",
        text="重新生成但不重算的叙事",
    )

    assert narrative_memory.get_current_artifact(
        root.game_id,
        root.branch_id,
        result.facts.settlement_id,
        "structured_action",
    ) == second
    assert [item.artifact_id for item in narrative_memory.list_artifacts(
        root.game_id,
        root.branch_id,
        result.facts.settlement_id,
    )] == [first.artifact_id, second.artifact_id]
    assert worlds.list_versions(root.game_id, root.branch_id) == before_versions


def test_memory_foreign_key_rejects_cross_branch_version(monkeypatch, tmp_path):
    _db_path, root = _store(monkeypatch, tmp_path)
    fork = worlds.create_branch_from_version(root.version_id)
    with pytest.raises(narrative_memory.NarrativeStoreConflictError):
        narrative_memory.append_memory(
            game_id=root.game_id,
            branch_id=root.branch_id,
            source_version_id=fork.version_id,
            mode="chat",
            phase="governance",
            chapter="chapter-a",
            topic_id="same-topic",
            kind="raw_recent",
            role="user",
            content="错误分支",
            created_world_hour=0,
        )


def test_boundary_summary_rejects_unknown_or_sibling_source_memory(monkeypatch, tmp_path):
    _db_path, root = _store(monkeypatch, tmp_path)
    source = _append(root, content="原分支记忆")
    fork = worlds.create_branch_from_version(root.version_id)
    sibling = _append(fork, content="子分支私有记忆")

    with pytest.raises(narrative_memory.NarrativeStoreConflictError):
        narrative_memory.append_boundary_summary(
            scope="chapter",
            content="错误摘要",
            source_memory_ids=[sibling.memory_id],
            game_id=root.game_id,
            branch_id=root.branch_id,
            source_version_id=root.version_id,
            mode="chat",
            phase="governance",
            chapter="chapter-b",
            topic_id="same-topic",
            created_world_hour=source.created_world_hour,
        )
    with pytest.raises(narrative_memory.NarrativeStoreConflictError):
        narrative_memory.append_boundary_summary(
            scope="chapter",
            content="不存在来源",
            source_memory_ids=[uuid4()],
            game_id=root.game_id,
            branch_id=root.branch_id,
            source_version_id=root.version_id,
            mode="chat",
            phase="governance",
            chapter="chapter-b",
            topic_id="same-topic",
            created_world_hour=source.created_world_hour,
        )


def test_database_rejects_cross_settlement_display_pointer_and_wrong_context_version(
    monkeypatch,
    tmp_path,
):
    _db_path, root = _store(monkeypatch, tmp_path)
    first_result = _commit(root, text="第一步")
    second_result = _commit(first_result.version, text="第二步")
    artifact = narrative_memory.save_artifact(
        game_id=root.game_id,
        branch_id=root.branch_id,
        settlement_id=first_result.facts.settlement_id,
        context_version_id=first_result.facts.result_version_id,
        path_id="structured_action",
        status="validated",
        text="第一步叙事",
    )

    with saves._connect() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO narrative_current_display (
                game_id, branch_id, settlement_id, path_id, artifact_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id, branch_id, settlement_id, path_id) DO UPDATE SET
                artifact_id = excluded.artifact_id
            """,
            (
                str(root.game_id), str(root.branch_id),
                str(second_result.facts.settlement_id), "structured_action",
                str(artifact.artifact_id),
                "2026-08-11T00:00:00+00:00",
            ),
        )

    with pytest.raises(narrative_memory.NarrativeStoreConflictError):
        narrative_memory.save_artifact(
            game_id=root.game_id,
            branch_id=root.branch_id,
            settlement_id=first_result.facts.settlement_id,
            context_version_id=second_result.facts.result_version_id,
            path_id="structured_action",
            status="validated",
            text="错误版本叙事",
        )
