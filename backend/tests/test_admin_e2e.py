from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import admin_routes
from api import routes as game_routes
from data.data_manager import DataManager
import data.data_manager as data_manager_module
import models.game as game_model


@pytest.fixture()
def admin_e2e_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source_manager = data_manager_module.get_data_manager()
    ministers = source_manager.get_ministers()
    events = source_manager.get_events()

    ministers_path = tmp_path / "ministers.json"
    ministers_path.write_text(
        json.dumps(ministers, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    events_dir = tmp_path / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    for script_id, payload in events.items():
        (events_dir / f"{script_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    manager = DataManager(ministers_path=ministers_path, events_dir=events_dir)
    monkeypatch.setattr(data_manager_module, "_DATA_MANAGER", manager, raising=True)
    monkeypatch.setattr(data_manager_module, "reload_script_registry", lambda force=True: None, raising=True)
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-admin")

    # Reset minister cache so /api/game/new will read from the temp DataManager paths.
    monkeypatch.setattr(game_model, "_INITIAL_MINISTERS_CACHE", None, raising=True)
    monkeypatch.setattr(game_model, "_INITIAL_MINISTERS_SIGNATURE", None, raising=True)

    db_path = tmp_path / "game_saves.db"
    monkeypatch.setattr(admin_routes, "DB_PATH", db_path, raising=True)
    with sqlite3.connect(str(db_path), timeout=5) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                game_time TEXT NOT NULL,
                created_at TEXT NOT NULL,
                state_json TEXT NOT NULL
            )
            """
        )

    app = FastAPI()
    app.include_router(game_routes.router)
    app.include_router(admin_routes.admin_router)
    client = TestClient(app)
    return client


def test_admin_end_to_end_verification(admin_e2e_client):
    client = admin_e2e_client
    headers = {"X-Admin-Password": "secret-admin"}

    # 1) server with ADMIN_PASSWORD + 2) authenticate
    verify_resp = client.get("/api/admin/verify", headers=headers)
    assert verify_resp.status_code == 200
    assert verify_resp.json() == {"ok": True}

    hot_reload_name = "端到端热加载大臣"
    before_state_resp = client.post("/api/game/new")
    assert before_state_resp.status_code == 200
    before_names = {item["name"] for item in before_state_resp.json()["ministers"]}
    assert hot_reload_name not in before_names

    # 3) CRUD each entity type
    minister_payload = {
        "name": hot_reload_name,
        "faction": "中立派",
        "personality_tags": [],
        "abilities": {"civil": 66, "military": 41, "diplomacy": 59},
        "status": "idle",
        "loyalty": 63,
        "positions": [],
        "is_eunuch": False,
        "entry_year": 1361,
        "entry_month": 7,
        "historical_note": "e2e minister",
    }
    create_minister_resp = client.post("/api/admin/ministers", headers=headers, json=minister_payload)
    assert create_minister_resp.status_code == 200
    assert create_minister_resp.json()["name"] == hot_reload_name

    get_minister_resp = client.get(f"/api/admin/ministers/{hot_reload_name}", headers=headers)
    assert get_minister_resp.status_code == 200
    assert get_minister_resp.json()["name"] == hot_reload_name

    updated_minister_payload = dict(minister_payload)
    updated_minister_payload["faction"] = "江南士绅"
    update_minister_resp = client.put(
        f"/api/admin/ministers/{hot_reload_name}",
        headers=headers,
        json=updated_minister_payload,
    )
    assert update_minister_resp.status_code == 200
    assert update_minister_resp.json()["faction"] == "江南士绅"

    positions_resp = client.get("/api/admin/positions", headers=headers)
    assert positions_resp.status_code == 200
    assert isinstance(positions_resp.json(), list)

    event_id = "admin-e2e-event"
    event_payload = {
        "script_id": event_id,
        "trigger_year": 1363,
        "trigger_month": 3,
        "title": "端到端事件",
        "is_blocking": False,
        "rich_description": "e2e",
        "historical_hint": "e2e-hint",
        "condition": None,
        "choices": [
            {
                "label": "保持现状",
                "description": "维持当前政策",
                "decrees": [],
                "loyalty_effects": [],
                "state_effects": {},
            }
        ],
    }
    create_event_resp = client.post("/api/admin/events", headers=headers, json=event_payload)
    assert create_event_resp.status_code == 200
    assert create_event_resp.json()["script_id"] == event_id

    get_event_resp = client.get(f"/api/admin/events/{event_id}", headers=headers)
    assert get_event_resp.status_code == 200
    assert get_event_resp.json()["script_id"] == event_id

    updated_event_payload = dict(event_payload)
    updated_event_payload["title"] = "端到端事件-更新"
    update_event_resp = client.put(f"/api/admin/events/{event_id}", headers=headers, json=updated_event_payload)
    assert update_event_resp.status_code == 200
    assert update_event_resp.json()["title"] == "端到端事件-更新"

    delete_event_resp = client.delete(f"/api/admin/events/{event_id}", headers=headers)
    assert delete_event_resp.status_code == 200
    assert delete_event_resp.json()["ok"] is True

    # 6) hot reload: admin edit should be visible in a new game initialization
    after_edit_state_resp = client.post("/api/game/new")
    assert after_edit_state_resp.status_code == 200
    after_edit_names = {item["name"] for item in after_edit_state_resp.json()["ministers"]}
    assert hot_reload_name in after_edit_names

    # 4) export -> modify -> import cycle
    export_resp = client.get("/api/admin/export", headers=headers)
    assert export_resp.status_code == 200
    bundle = export_resp.json()
    assert "ministers" in bundle and "events" in bundle and "positions" in bundle

    imported_name = "端到端导入大臣"
    bundle["ministers"].append(
        {
            "name": imported_name,
            "faction": "中立派",
            "personality_tags": [],
            "abilities": {"civil": 51, "military": 52, "diplomacy": 53},
            "status": "idle",
            "loyalty": 54,
            "positions": [],
            "is_eunuch": False,
            "entry_year": 1362,
            "entry_month": 8,
            "historical_note": "e2e imported",
        }
    )

    validate_import_resp = client.post("/api/admin/import/validate", headers=headers, json=bundle)
    assert validate_import_resp.status_code == 200
    assert validate_import_resp.json()["ok"] is True

    import_resp = client.post("/api/admin/import", headers=headers, json=bundle)
    assert import_resp.status_code == 200
    assert import_resp.json()["ok"] is True

    # 5) game still loads correctly after admin edits/imports
    after_import_state_resp = client.post("/api/game/new")
    assert after_import_state_resp.status_code == 200
    final_names = {item["name"] for item in after_import_state_resp.json()["ministers"]}
    assert hot_reload_name in final_names
    assert imported_name in final_names
