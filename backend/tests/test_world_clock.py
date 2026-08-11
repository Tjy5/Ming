import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from engine.calendar import projection_from_absolute_hour
from engine.core import advance_time
from main import app
from models.game import GameState, GameTime, create_initial_state
from models.world import CalendarProjection, WorldClock


def test_world_clock_contract_round_trips_and_rejects_unknown_fields():
    clock = WorldClock(absolute_hour=123)
    assert WorldClock.model_validate(clock.model_dump(mode="json")) == clock
    with pytest.raises(ValidationError):
        WorldClock.model_validate({**clock.model_dump(mode="json"), "local_time": 123})


def test_calendar_projection_rejects_day_beyond_month_length():
    payload = projection_from_absolute_hour(0).model_dump(mode="json")
    payload["day"] = 30
    with pytest.raises(ValidationError):
        CalendarProjection.model_validate(payload)


def test_new_world_binds_calendar_v1_at_the_epoch():
    state = create_initial_state()
    assert state.time.clock is not None
    assert state.time.calendar is not None
    assert state.time.clock.absolute_hour == 0
    assert state.time.clock.calendar_version == "yuanming-calendar-v1"
    assert state.world_metadata.calendar_schema_version == state.time.clock.calendar_version
    assert state.time.time_migration_source == "initial_world"
    assert (
        state.time.calendar.year,
        state.time.calendar.month,
        state.time.calendar.day,
        state.time.calendar.double_hour_name,
    ) == (1328, 10, 1, "子")


def test_legacy_advance_month_keeps_clock_and_projection_in_sync():
    state = create_initial_state()
    advance_time(state)
    assert state.time.clock is not None
    assert state.time.calendar is not None
    assert state.time.clock.absolute_hour == 29 * 24
    assert (
        state.time.year,
        state.time.month,
        state.time.calendar.year,
        state.time.calendar.month,
        state.time.calendar.day,
    ) == (1328, 11, 1328, 11, 1)


def test_compatibility_writer_reanchors_a_manually_changed_legacy_projection():
    state = create_initial_state()
    state.time.year = 1356
    state.time.month = 3
    advance_time(state)
    assert state.time.calendar is not None
    assert (state.time.year, state.time.month) == (1356, 4)
    assert (state.time.calendar.year, state.time.calendar.month) == (1356, 4)


def test_game_state_json_round_trip_preserves_exact_clock_identity():
    state = create_initial_state()
    restored = GameState.model_validate_json(state.model_dump_json())
    assert restored.time == state.time


def test_openapi_publishes_clock_and_calendar_models_through_game_time():
    schemas = app.openapi()["components"]["schemas"]
    assert "GameTime" in schemas
    assert "WorldClock" in schemas
    assert "CalendarProjection" in schemas
    properties = schemas["GameTime"]["properties"]
    assert "WorldClock" in str(properties["clock"])
    assert "CalendarProjection" in str(properties["calendar"])
    for schema_name in (
        "Duration",
        "ElapsedSegmentPlan",
        "Activity",
        "ActivityCheckpoint",
        "ActivityContinueRequest",
        "ActivityBatchExecutionResponse",
    ):
        assert schema_name in schemas
    paths = app.openapi()["paths"]
    assert "/api/activities/{game_id}/{branch_id}/{activity_id}" in paths
    assert "/api/activities/{activity_id}/continue" in paths


def test_old_game_time_payload_remains_additively_valid():
    legacy = GameTime.model_validate(
        {"year": 1356, "month": 3, "era_name": "至正", "era_year": 16}
    )
    assert legacy.clock is None
    assert legacy.calendar is None


def test_production_code_has_no_direct_year_or_month_assignment():
    backend_root = Path(__file__).resolve().parents[1]
    direct_write = re.compile(r"\.time\.(?:year|month)\s*(?:\+=|-=|=(?!=))")
    offenders: list[str] = []
    for path in backend_root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if direct_write.search(line):
                offenders.append(f"{path.relative_to(backend_root)}:{line_number}")
    assert offenders == []


def test_production_routes_have_no_parallel_time_writer_or_terminal_year_gate():
    backend_root = Path(__file__).resolve().parents[1]
    forbidden_by_scope = {
        backend_root / "api": re.compile(
            r"\b(?:set_game_time_projection|advance_game_time|prepare_month_advance|"
            r"finalize_month_advance|advance_month)\s*\(",
        ),
        backend_root / "trpg": re.compile(r"\bset_game_time_projection\s*\("),
    }
    offenders: list[str] = []
    for scope, pattern in forbidden_by_scope.items():
        for path in scope.rglob("*.py"):
            if path.name == "action_service.py":
                continue
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(backend_root)}:{line_number}")
    assert offenders == []

    production_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in backend_root.rglob("*.py")
        if "tests" not in path.parts
    )
    assert "FINAL_JUDGEMENT_YEAR" not in production_text
    assert "FINAL_JUDGEMENT_MONTH" not in production_text
    assert "COMPATIBLE_YEAR_MAX" not in production_text
