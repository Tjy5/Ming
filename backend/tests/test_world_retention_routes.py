from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import state as api_state
from db import saves, worlds
from main import app
from models.game import create_initial_state


@pytest.fixture(autouse=True)
def _isolated_world_store(monkeypatch, tmp_path):
    old_state = api_state._state
    old_ref = api_state._get_world_head_ref()
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "retention-routes.db")
    saves.init_db()
    api_state._world_head_cache.clear()
    try:
        yield
    finally:
        api_state._state = old_state
        api_state._world_head_cache.restore_ref(old_ref)


def test_public_bookmark_and_report_only_retention_routes_are_typed() -> None:
    root = worlds.create_game_with_root(create_initial_state())
    bookmark = worlds.create_bookmark(
        root.game_id,
        root.branch_id,
        root.version_id,
        "continuity-root",
    )

    with TestClient(app) as client:
        bookmarks = client.get(f"/api/worlds/{root.game_id}/bookmarks")
        retention = client.get(
            f"/api/worlds/{root.game_id}/retention",
            params={"branch_id": str(root.branch_id), "recent_limit": 1},
        )

    assert bookmarks.status_code == 200, bookmarks.text
    assert bookmarks.json()["bookmarks"][0]["bookmark_id"] == str(bookmark.bookmark_id)
    assert retention.status_code == 200, retention.text
    report = retention.json()
    assert str(root.version_id) in report["protected_version_ids"]
    assert report["delete_version_ids"] == []

