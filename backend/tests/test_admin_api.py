from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import admin_auth, admin_routes
from data.data_manager import DataManager
import data.data_manager as data_manager_module


@pytest.fixture()
def admin_test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    monkeypatch.setenv("ADMIN_PASSWORD", "secret-admin")
    return manager, db_path


def test_admin_auth_rejects_wrong_password(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "correct")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(admin_auth.require_admin("wrong"))
    assert exc_info.value.status_code == 401


def test_admin_auth_accepts_correct_password(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "correct")
    asyncio.run(admin_auth.require_admin("correct"))


def test_admin_verify_endpoint_requires_password(monkeypatch: pytest.MonkeyPatch):
    app = FastAPI()
    app.include_router(admin_routes.admin_router)
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    client = TestClient(app)

    response = client.get("/api/admin/verify")
    assert response.status_code == 401


def test_admin_verify_endpoint_accepts_password(monkeypatch: pytest.MonkeyPatch):
    app = FastAPI()
    app.include_router(admin_routes.admin_router)
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    client = TestClient(app)

    response = client.get("/api/admin/verify", headers={"X-Admin-Password": "secret"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_admin_ministers_endpoint_requires_password_header(admin_test_env):
    _manager, _db = admin_test_env
    app = FastAPI()
    app.include_router(admin_routes.admin_router)
    client = TestClient(app)

    unauthorized = client.get("/api/admin/ministers")
    assert unauthorized.status_code == 401

    authorized = client.get("/api/admin/ministers", headers={"X-Admin-Password": "secret-admin"})
    assert authorized.status_code == 200
    assert isinstance(authorized.json(), list)


def test_admin_minister_crud(admin_test_env):
    _manager, _db = admin_test_env
    payload = {
        "name": "测试大臣甲",
        "faction": "江南士绅",
        "personality_tags": ["儒雅"],
        "abilities": {"civil": 60, "military": 20, "diplomacy": 55},
        "status": "idle",
        "loyalty": 55,
        "positions": [],
        "is_eunuch": False,
        "entry_year": 1357,
        "entry_month": 1,
        "historical_note": "测试数据",
    }

    created = asyncio.run(admin_routes.admin_create_minister(payload, None))
    assert created["name"] == "测试大臣甲"

    ministers = asyncio.run(admin_routes.admin_get_ministers(None))
    assert any(item["name"] == "测试大臣甲" for item in ministers)

    updated_payload = dict(payload)
    updated_payload["faction"] = "幕府文臣"
    updated = asyncio.run(admin_routes.admin_update_minister("测试大臣甲", updated_payload, None))
    assert updated["faction"] == "幕府文臣"

    deleted = asyncio.run(admin_routes.admin_delete_minister("测试大臣甲", None))
    assert deleted["ok"] is True
    ministers_after = asyncio.run(admin_routes.admin_get_ministers(None))
    assert not any(item["name"] == "测试大臣甲" for item in ministers_after)


def _build_minister_payload(name: str, *, position: str, category: str) -> dict:
    tags: list[str] = []
    faction = "江南士绅"
    is_eunuch = False

    if category == "NOBLE":
        tags = ["勋贵"]
        faction = "汉政权"
    elif category == "EUNUCH":
        is_eunuch = True
    elif "大学士" in position:
        tags = ["翰林"]

    return {
        "name": name,
        "faction": faction,
        "personality_tags": tags,
        "abilities": {"civil": 65, "military": 35, "diplomacy": 50},
        "status": "idle",
        "loyalty": 60,
        "positions": [position],
        "is_eunuch": is_eunuch,
        "entry_year": 1359,
        "entry_month": 1,
        "historical_note": "测试任职约束",
    }


def test_admin_update_minister_idempotent(admin_test_env):
    _manager, _db = admin_test_env
    payload = {
        "name": "测试大臣幂等",
        "faction": "江南士绅",
        "personality_tags": ["儒雅"],
        "abilities": {"civil": 70, "military": 20, "diplomacy": 60},
        "status": "idle",
        "loyalty": 58,
        "positions": [],
        "is_eunuch": False,
        "entry_year": 1358,
        "entry_month": 4,
        "historical_note": "幂等测试",
    }

    asyncio.run(admin_routes.admin_create_minister(payload, None))
    update_payload = dict(payload)
    update_payload["faction"] = "幕府文臣"

    first = asyncio.run(admin_routes.admin_update_minister("测试大臣幂等", update_payload, None))
    second = asyncio.run(admin_routes.admin_update_minister("测试大臣幂等", update_payload, None))

    assert first == second
    fetched = asyncio.run(admin_routes.admin_get_minister("测试大臣幂等", None))
    assert fetched == first


def test_admin_create_minister_rejects_historical_constraint(admin_test_env):
    _manager, _db = admin_test_env
    positions = asyncio.run(admin_routes.admin_get_positions(None))
    eunuch_position = next(item for item in positions if item["category"] == "EUNUCH")

    payload = {
        "name": "非法任命测试",
        "faction": "江南士绅",
        "personality_tags": [],
        "abilities": {"civil": 40, "military": 20, "diplomacy": 30},
        "status": "idle",
        "loyalty": 40,
        "positions": [eunuch_position["name"]],
        "is_eunuch": False,
        "entry_year": 1360,
        "entry_month": 1,
        "historical_note": "应当被拒绝",
    }

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(admin_routes.admin_create_minister(payload, None))
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "invalid_minister"


def test_admin_create_minister_rejects_unique_position_conflict(admin_test_env):
    """Unique position conflicts now warn instead of error on create/save;
    the import validation still enforces uniqueness via strict mode."""
    _manager, _db = admin_test_env
    positions = asyncio.run(admin_routes.admin_get_positions(None))
    candidate = next(item for item in positions if item["unique"])
    for holder_name in candidate["holders"]:
        holder_payload = asyncio.run(admin_routes.admin_get_minister(holder_name, None))
        holder_payload["positions"] = [
            position
            for position in holder_payload.get("positions", [])
            if position != candidate["name"]
        ]
        asyncio.run(admin_routes.admin_update_minister(holder_name, holder_payload, None))

    first_payload = _build_minister_payload(
        "唯一官职持有者甲",
        position=candidate["name"],
        category=candidate["category"],
    )
    second_payload = _build_minister_payload(
        "唯一官职持有者乙",
        position=candidate["name"],
        category=candidate["category"],
    )

    asyncio.run(admin_routes.admin_create_minister(first_payload, None))
    asyncio.run(admin_routes.admin_create_minister(second_payload, None))
    # Verify both were created
    all_ministers = asyncio.run(admin_routes.admin_get_ministers(None))
    names = {m["name"] for m in all_ministers}
    assert "唯一官职持有者甲" in names
    assert "唯一官职持有者乙" in names


def test_admin_event_crud(admin_test_env):
    _manager, _db = admin_test_env
    payload = {
        "script_id": "admin-test-event",
        "trigger_year": 1360,
        "trigger_month": 6,
        "title": "管理员测试事件",
        "is_blocking": False,
        "rich_description": "测试事件描述",
        "historical_hint": "测试历史提示。",
        "condition": None,
        "choices": [
            {
                "label": "保持现状",
                "description": "不做调整",
                "decrees": [],
                "loyalty_effects": [],
                "state_effects": {},
            }
        ],
    }

    created = asyncio.run(admin_routes.admin_create_event(payload, None))
    assert created["script_id"] == "admin-test-event"

    fetched = asyncio.run(admin_routes.admin_get_event("admin-test-event", None))
    assert fetched["title"] == "管理员测试事件"

    payload["title"] = "管理员测试事件-更新"
    updated = asyncio.run(admin_routes.admin_update_event("admin-test-event", payload, None))
    assert updated["title"] == "管理员测试事件-更新"

    deleted = asyncio.run(admin_routes.admin_delete_event("admin-test-event", None))
    assert deleted["ok"] is True


def test_admin_event_rejects_trigger_year_out_of_range(admin_test_env):
    _manager, _db = admin_test_env
    base_payload = {
        "script_id": "admin-invalid-year",
        "trigger_month": 6,
        "title": "年份非法事件",
        "is_blocking": False,
        "rich_description": "测试",
        "historical_hint": "测试",
        "condition": None,
        "choices": [
            {
                "label": "保持现状",
                "description": "不做调整",
                "decrees": [],
                "loyalty_effects": [],
                "state_effects": {},
            }
        ],
    }

    payload_low = dict(base_payload)
    payload_low["trigger_year"] = 1327
    with pytest.raises(HTTPException) as low_exc:
        asyncio.run(admin_routes.admin_create_event(payload_low, None))
    assert low_exc.value.status_code == 422
    assert low_exc.value.detail["error_code"] == "invalid_event"

    payload_high = dict(base_payload)
    payload_high["script_id"] = "admin-invalid-year-high"
    payload_high["trigger_year"] = 1369
    with pytest.raises(HTTPException) as high_exc:
        asyncio.run(admin_routes.admin_create_event(payload_high, None))
    assert high_exc.value.status_code == 422
    assert high_exc.value.detail["error_code"] == "invalid_event"


def test_admin_event_accepts_trigger_year_boundaries(admin_test_env):
    _manager, _db = admin_test_env
    payload_low = {
        "script_id": "admin-year-lower-bound",
        "trigger_year": 1328,
        "trigger_month": 1,
        "title": "合法下边界年份",
        "is_blocking": False,
        "rich_description": "测试",
        "historical_hint": "测试",
        "condition": None,
        "choices": [
            {
                "label": "保持现状",
                "description": "不做调整",
                "decrees": [],
                "loyalty_effects": [],
                "state_effects": {},
            }
        ],
    }
    payload_high = dict(payload_low)
    payload_high["script_id"] = "admin-year-upper-bound"
    payload_high["trigger_year"] = 1368
    payload_high["trigger_month"] = 12
    payload_high["title"] = "合法上边界年份"

    created_low = asyncio.run(admin_routes.admin_create_event(payload_low, None))
    created_high = asyncio.run(admin_routes.admin_create_event(payload_high, None))
    assert created_low["trigger_year"] == 1328
    assert created_high["trigger_year"] == 1368


def test_admin_event_delete_rejected_when_active_in_saves(admin_test_env):
    _manager, db_path = admin_test_env
    payload = {
        "script_id": "admin-test-active-event",
        "trigger_year": 1360,
        "trigger_month": 7,
        "title": "管理员测试激活事件",
        "is_blocking": False,
        "rich_description": "测试事件描述",
        "historical_hint": "测试历史提示。",
        "condition": None,
        "choices": [
            {
                "label": "保持现状",
                "description": "不做调整",
                "decrees": [],
                "loyalty_effects": [],
                "state_effects": {},
            }
        ],
    }
    asyncio.run(admin_routes.admin_create_event(payload, None))

    state_json = json.dumps(
        {
            "active_events": [
                {"script_id": "admin-test-active-event", "name": "x"},
            ]
        },
        ensure_ascii=False,
    )
    with sqlite3.connect(str(db_path), timeout=5) as conn:
        conn.execute(
            "INSERT INTO saves (name, game_time, created_at, state_json) VALUES (?, ?, ?, ?)",
            ("test", "至正二十年七月", "2026-02-22T00:00:00+00:00", state_json),
        )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(admin_routes.admin_delete_event("admin-test-active-event", None))
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "event_active_in_saves"


def test_admin_import_export_roundtrip(admin_test_env):
    _manager, _db = admin_test_env
    exported = asyncio.run(admin_routes.admin_export(None))
    assert "ministers" in exported
    assert "events" in exported
    assert "positions" in exported

    imported = asyncio.run(admin_routes.admin_import(exported, None))
    assert imported["ok"] is True
    assert imported["ministers_count"] == len(exported["ministers"])
    assert imported["events_count"] == len(exported["events"])


def test_admin_import_validate_success_without_mutation(admin_test_env):
    _manager, _db = admin_test_env
    exported_before = asyncio.run(admin_routes.admin_export(None))

    validated = asyncio.run(admin_routes.admin_import_validate(exported_before, None))
    assert validated["ok"] is True
    assert validated["ministers_count"] == len(exported_before["ministers"])
    assert validated["events_count"] == len(exported_before["events"])

    exported_after = asyncio.run(admin_routes.admin_export(None))
    assert exported_after["ministers"] == exported_before["ministers"]
    assert exported_after["events"] == exported_before["events"]
    assert exported_after["positions"] == exported_before["positions"]


def test_admin_import_validate_rejects_invalid_payload(admin_test_env):
    _manager, _db = admin_test_env
    payload = {
        "ministers": [],
        "events": "not-a-list-or-map",
    }
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(admin_routes.admin_import_validate(payload, None))
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "invalid_import"


def test_admin_import_validate_rejects_duplicate_script_ids(admin_test_env):
    _manager, _db = admin_test_env
    payload = asyncio.run(admin_routes.admin_export(None))
    first = payload["events"][0]
    payload["events"] = [first, dict(first)]

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(admin_routes.admin_import_validate(payload, None))
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "invalid_import_events"


def test_admin_create_event_rejects_invalid_condition(admin_test_env):
    _manager, _db = admin_test_env
    payload = {
        "script_id": "admin-invalid-condition",
        "trigger_year": 1360,
        "trigger_month": 8,
        "title": "无效条件事件",
        "is_blocking": False,
        "rich_description": "测试事件描述",
        "historical_hint": "测试历史提示。",
        "condition": {"type": "state_field_gt", "field": "unknown_field", "value": 1},
        "choices": [
            {
                "label": "保持现状",
                "description": "不做调整",
                "decrees": [],
                "loyalty_effects": [],
                "state_effects": {},
            }
        ],
    }
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(admin_routes.admin_create_event(payload, None))
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "invalid_event"


def test_admin_create_event_rejects_empty_choice_description(admin_test_env):
    _manager, _db = admin_test_env
    payload = {
        "script_id": "admin-empty-choice-description",
        "trigger_year": 1360,
        "trigger_month": 8,
        "title": "空描述事件",
        "is_blocking": False,
        "rich_description": "测试事件描述",
        "historical_hint": "测试历史提示。",
        "condition": None,
        "choices": [
            {
                "label": "保持现状",
                "description": "",
                "decrees": [],
                "loyalty_effects": [],
                "state_effects": {},
            }
        ],
    }
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(admin_routes.admin_create_event(payload, None))
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "invalid_event"


@given(
    seed=st.integers(min_value=1, max_value=99999),
    civil=st.integers(min_value=0, max_value=100),
    military=st.integers(min_value=0, max_value=100),
    diplomacy=st.integers(min_value=0, max_value=100),
    loyalty=st.integers(min_value=0, max_value=100),
    entry_year=st.integers(min_value=1328, max_value=1368),
    entry_month=st.integers(min_value=1, max_value=12),
)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_admin_minister_roundtrip_pbt(
    admin_test_env,
    seed: int,
    civil: int,
    military: int,
    diplomacy: int,
    loyalty: int,
    entry_year: int,
    entry_month: int,
):
    _manager, _db = admin_test_env
    name = f"pbt-minister-{seed}"
    payload = {
        "name": name,
        "faction": "中立派",
        "personality_tags": [],
        "abilities": {"civil": civil, "military": military, "diplomacy": diplomacy},
        "status": "idle",
        "loyalty": loyalty,
        "positions": [],
        "is_eunuch": False,
        "entry_year": entry_year,
        "entry_month": entry_month,
        "historical_note": f"pbt-{seed}",
    }

    if any(item["name"] == name for item in asyncio.run(admin_routes.admin_get_ministers(None))):
        asyncio.run(admin_routes.admin_delete_minister(name, None))

    created = asyncio.run(admin_routes.admin_create_minister(payload, None))
    fetched = asyncio.run(admin_routes.admin_get_minister(name, None))
    assert fetched == created

    deleted = asyncio.run(admin_routes.admin_delete_minister(name, None))
    assert deleted["ok"] is True


@given(seed=st.integers(min_value=1, max_value=99999))
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_data_manager_atomic_write_pbt(seed: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source_manager = data_manager_module.get_data_manager()
    ministers = source_manager.get_ministers()

    ministers_path = tmp_path / "ministers.json"
    ministers_path.write_text(
        json.dumps(ministers, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    events_dir = tmp_path / "events"
    events_dir.mkdir(parents=True, exist_ok=True)

    manager = DataManager(ministers_path=ministers_path, events_dir=events_dir)
    mutated = [dict(item) for item in ministers]
    candidate = dict(mutated[0])
    candidate["name"] = f"atomic-write-{seed}"
    candidate["positions"] = []
    mutated.append(candidate)

    def _broken_replace(src: str, dst: Path) -> None:
        raise OSError("simulated os.replace failure")

    monkeypatch.setattr(data_manager_module.os, "replace", _broken_replace, raising=True)

    with pytest.raises(OSError):
        manager.write_ministers(mutated)

    persisted = json.loads(ministers_path.read_text(encoding="utf-8"))
    assert persisted == ministers


def test_data_manager_hot_reload_for_ministers(admin_test_env):
    manager, _db = admin_test_env
    before = manager.get_ministers()
    target_name = "hot-reload-minister"
    assert all(item["name"] != target_name for item in before)

    mutated = [dict(item) for item in before]
    candidate = dict(mutated[0])
    candidate["name"] = target_name
    candidate["positions"] = []
    mutated.append(candidate)

    time.sleep(0.01)
    manager.ministers_path.write_text(
        json.dumps(mutated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    after = manager.get_ministers()
    assert any(item["name"] == target_name for item in after)
    assert len(after) == len(before) + 1


def test_data_manager_hot_reload_for_events(admin_test_env):
    manager, _db = admin_test_env
    before = manager.get_events()
    script_id = "hot-reload-event"
    assert script_id not in before

    template = dict(next(iter(before.values())))
    template["script_id"] = script_id
    time.sleep(0.01)
    (manager.events_dir / f"{script_id}.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    after = manager.get_events()
    assert script_id in after
