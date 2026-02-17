import asyncio

import pytest
from fastapi import HTTPException

from ai.provider import MockProvider, ResilientProvider
from api import routes
from models.enums import DecreeType, PersonnelAction
from models.game import (
    CourtAssembly,
    HistoryEntry,
    PolicySuggestion,
    StructuredDecree,
    create_initial_state,
)


@pytest.fixture(autouse=True)
def _restore_route_globals():
    old_state = routes._state
    old_provider = routes._provider
    try:
        yield
    finally:
        routes._state = old_state
        routes._provider = old_provider


def _mock_provider():
    return ResilientProvider(MockProvider(), timeout=1, retries=1)


def test_execute_decree_is_atomic_when_later_decree_fails_precondition():
    routes._provider = _mock_provider()
    routes._state = create_initial_state()
    routes._state.treasury = 25
    before = routes._state.model_dump()

    req = routes.DecreeRequest(
        decrees=[
            StructuredDecree(type=DecreeType.RECRUIT_TROOPS),
            StructuredDecree(type=DecreeType.TAX_DECREASE),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(req))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "precondition_failed"
    assert routes._state is not None
    assert routes._state.model_dump() == before


def test_personnel_target_must_exist():
    routes._provider = _mock_provider()
    routes._state = create_initial_state()
    before = routes._state.model_dump()

    req = routes.DecreeRequest(
        decrees=[
            StructuredDecree(
                type=DecreeType.PERSONNEL,
                target="不存在的人",
                sub_action=PersonnelAction.APPOINT,
            ),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(req))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "invalid_decree"
    assert "目标人物不存在" in exc_info.value.detail["message"]
    assert routes._state is not None
    assert routes._state.model_dump() == before


def test_get_history_normalizes_negative_offset_and_small_limit():
    routes._state = create_initial_state()
    routes._state.history_log = [
        HistoryEntry(year=1627, month=i, decree_type="x")
        for i in range(1, 6)
    ]

    result = asyncio.run(routes.get_history(offset=-2, limit=0))
    assert result["offset"] == 0
    assert result["limit"] == 1
    assert len(result["entries"]) == 1
    assert result["entries"][0]["month"] == 1


def test_execute_decree_summary_includes_action_implications_for_commentary():
    routes._provider = _mock_provider()
    routes._state = create_initial_state()

    req = routes.DecreeRequest(
        decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)]
    )
    result = asyncio.run(routes.execute_decree(req))

    summary = result["turn_summary"]
    assert summary is not None
    assert summary["action_implications"]
    assert any("严刑峻法" in item for item in summary["action_implications"])
    if not summary["major_events"]:
        assert "朝政有变" in summary["commentary"]


def test_execute_decree_wait_turn_includes_memorial_triggers():
    routes._provider = _mock_provider()
    state = create_initial_state()
    state.factions[0].satisfaction = 10
    routes._state = state

    result = asyncio.run(routes.execute_decree(routes.DecreeRequest(source_script_id="script-1")))

    assert "memorial_triggers" in result
    assert len(result["memorial_triggers"]) >= 1


def test_adopt_suggestion_includes_memorial_triggers():
    routes._provider = _mock_provider()
    state = create_initial_state()
    state.factions[0].satisfaction = 10
    state.last_assembly = CourtAssembly(
        topic="严刑峻法之议",
        decree_type=DecreeType.HARSH_PUNISHMENT,
        suggestions=[
            PolicySuggestion(
                title="严刑整肃",
                description="以重典整饬朝纲",
                related_decree=StructuredDecree(type=DecreeType.HARSH_PUNISHMENT),
            )
        ],
    )
    routes._state = state

    result = asyncio.run(routes.adopt_suggestion(routes.AdoptSuggestionRequest(suggestion_index=0)))

    assert "memorial_triggers" in result
    assert len(result["memorial_triggers"]) >= 1
