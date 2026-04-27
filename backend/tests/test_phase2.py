import copy
import json
import random
import pytest
from pydantic import ValidationError

from pathlib import Path

import models.game as game_model
from models.game import (
    GameState, GameTime, Faction, Region, Minister, MinisterAbilities,
    create_initial_state, clamp_state, INITIAL_MINISTERS, INITIAL_FACTIONS,
)
from models.enums import (
    DecreeType, MinisterStatus, PersonnelAction, TaxContribution,
)
from models.positions import resolve_position
from engine.core import (
    process_decree, resolve_era, apply_minister_transition, inject_script_events,
)
from api.debate_helpers import select_debate_ministers
from db.saves import _migrate_save


# ── 12.1 Minister/MinisterAbilities model validation ───

class TestMinisterModel:
    def test_valid_minister(self):
        m = Minister(name="张三", faction="东林党", personality_tags=["忠诚", "刚烈"],
                     abilities=MinisterAbilities(civil=80, military=50, diplomacy=60))
        assert m.status == MinisterStatus.ACTIVE

    def test_abilities_bounds(self):
        with pytest.raises(ValidationError):
            MinisterAbilities(civil=101, military=50, diplomacy=50)
        with pytest.raises(ValidationError):
            MinisterAbilities(civil=-1, military=50, diplomacy=50)

    def test_status_enum(self):
        m = Minister(name="x", faction="y", status=MinisterStatus.IDLE)
        assert m.status == MinisterStatus.IDLE

    def test_tags_max_4(self):
        with pytest.raises(ValidationError):
            Minister(name="x", faction="y", personality_tags=["a", "b", "c", "d", "e"])


# ── 12.2 INITIAL_MINISTERS data integrity ──────────────

class TestInitialMinisters:
    def test_count(self):
        assert len(INITIAL_MINISTERS) > 0

    def test_unique_names(self):
        names = [m.name for m in INITIAL_MINISTERS]
        assert len(names) == len(set(names))

    def test_valid_factions(self):
        valid = {f.name for f in INITIAL_FACTIONS}
        for m in INITIAL_MINISTERS:
            assert m.faction in valid

    def test_all_abilities_in_bounds(self):
        for m in INITIAL_MINISTERS:
            for field in ("civil", "military", "diplomacy"):
                v = getattr(m.abilities, field)
                assert 0 <= v <= 100

    def test_all_tags_max_4(self):
        for m in INITIAL_MINISTERS:
            assert len(m.personality_tags) <= 4

    def test_roster_meets_100_plus_target(self):
        assert len(INITIAL_MINISTERS) >= 100

    def test_faction_distribution_min_5(self):
        faction_counts: dict[str, int] = {}
        for m in INITIAL_MINISTERS:
            faction_counts[m.faction] = faction_counts.get(m.faction, 0) + 1
        for faction, count in faction_counts.items():
            assert count >= 5, f"Faction {faction} has only {count} ministers"

    def test_entry_dates_in_range(self):
        for m in INITIAL_MINISTERS:
            assert 1550 <= m.entry_year <= 1650, f"{m.name} entry_year={m.entry_year}"
            assert 1 <= m.entry_month <= 12, f"{m.name} entry_month={m.entry_month}"

    def test_all_required_fields_present(self):
        required = ["name", "faction", "positions", "entry_year", "entry_month",
                     "loyalty", "abilities", "historical_note", "personality_tags", "status"]
        for m in INITIAL_MINISTERS:
            for field in required:
                assert getattr(m, field, None) is not None, f"{m.name} missing {field}"

    def test_all_positions_valid(self):
        for m in INITIAL_MINISTERS:
            for pos in m.positions:
                assert resolve_position(pos) is not None, \
                    f"{m.name} has unresolved position: {pos}"

    def test_names_strip_consistency(self):
        for m in INITIAL_MINISTERS:
            assert m.name == m.name.strip(), f"'{m.name}' has leading/trailing whitespace"

    def test_runtime_loader_does_not_merge_review_metadata(self, tmp_path, monkeypatch):
        runtime_path = tmp_path / "ministers.json"
        review_path = tmp_path / "ministers_review.json"
        runtime_path.write_text(
            json.dumps(
                [
                    {
                        "name": "测试大臣",
                        "faction": INITIAL_FACTIONS[0].name,
                        "personality_tags": ["谨慎"],
                        "abilities": {"civil": 50, "military": 40, "diplomacy": 30},
                        "status": "active",
                        "loyalty": 55,
                        "position": "东阁大学士",
                        "entry_year": 1627,
                        "entry_month": 8,
                        "historical_note": "测试运行时数据。",
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        review_path.write_text(
            json.dumps(
                [
                    {
                        "name": "测试大臣",
                        "birth_year": 1600,
                        "death_year": 1650,
                        "office_history": ["不应进入运行时履历"],
                        "related_events": ["不应进入运行时事件"],
                        "major_contributions": ["不应进入运行时事功"],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(game_model, "_try_get_data_manager", lambda: None)
        monkeypatch.setattr(game_model, "_MINISTERS_JSON", runtime_path)
        monkeypatch.setattr(game_model, "_MINISTERS_REVIEW_JSON", review_path, raising=False)

        minister = game_model._read_initial_ministers_file()[0]

        assert minister.biography == ""
        assert minister.major_contributions == []


# ── 12.3 Conditional script injection ─────────────────

class TestConditionalInjection:
    def _state_at(self, year, month, **kw):
        return GameState(
            time=GameTime(year=year, month=month, era_name="天启", era_year=7),
            factions=kw.get("factions", [Faction(name="test", satisfaction=50, influence=50, rebellion_risk=10)]),
            regions=kw.get("regions", [Region(name="test", stability=50, garrison=10000, tax_contribution=TaxContribution.MEDIUM)]),
            ministers=kw.get("ministers", []),
        )

    def test_unconditional_event_injects(self):
        # eunuch-party-purge-1627-12 has condition=None, always fires
        state = self._state_at(1627, 12)
        injected = inject_script_events(state)
        assert "阉党清算·边镇欠饷" in injected

    def test_conditional_event_pass_injects(self):
        # yuan-chonghuan-arrest at 1629/12 requires "jisi-invasion" resolved
        state = self._state_at(1629, 12)
        state.resolved_script_ids = {"jisi-invasion"}
        injected = inject_script_events(state)
        assert any("袁崇焕" in t for t in injected)

    def test_conditional_event_fail_skips(self):
        # yuan-chonghuan-arrest condition fails without "jisi-invasion" resolved
        state = self._state_at(1629, 12)
        state.resolved_script_ids = set()
        injected = inject_script_events(state)
        assert not any("袁崇焕" in t for t in injected)

    def test_wrong_month_not_injected(self):
        state = self._state_at(1627, 11)
        injected = inject_script_events(state)
        assert "阉党清算·边镇欠饷" not in injected

    def test_idempotent(self):
        state = self._state_at(1627, 12)
        inject_script_events(state)
        count_before = len(state.active_events)
        inject_script_events(state)
        assert len(state.active_events) == count_before


# ── 12.4 Debate minister selection ────────────────────

class TestDebateMinisterSelection:
    def test_opposing_factions(self):
        state = create_initial_state()
        result = select_debate_ministers(state, DecreeType.TAX_INCREASE)
        if result:
            a, b = result
            assert a.faction != b.faction

    def test_returns_none_when_all_idle(self):
        state = create_initial_state()
        for m in state.ministers:
            m.status = MinisterStatus.IDLE
        assert select_debate_ministers(state, DecreeType.TAX_INCREASE) is None

    def test_permutation_invariance(self):
        state = create_initial_state()
        r1 = select_debate_ministers(state, DecreeType.TAX_INCREASE)
        random.shuffle(state.ministers)
        r2 = select_debate_ministers(state, DecreeType.TAX_INCREASE)
        if r1 and r2:
            assert {r1[0].name, r1[1].name} == {r2[0].name, r2[1].name}


# ── 12.5 Start time 1627/10 and era resolution ────────

class TestStartTimeAndEra:
    def test_initial_state_time(self):
        state = create_initial_state()
        assert state.time.year == 1627
        assert state.time.month == 8
        assert state.time.era_name == "天启"
        assert state.time.era_year == 7

    def test_era_resolution_tianqi(self):
        assert resolve_era(1627) == ("天启", 7)

    def test_era_resolution_chongzhen(self):
        assert resolve_era(1628) == ("崇祯", 1)
        assert resolve_era(1630) == ("崇祯", 3)

    def test_era_resolution_boundary(self):
        assert resolve_era(1621) == ("天启", 1)
        assert resolve_era(1644) == ("崇祯", 17)


# ── 12.6 Save migration ──────────────────────────────

class TestSaveMigration:
    def _old_save(self, include_ministers=False, ministers_val=None):
        data = {
            "time": {"year": 1630, "month": 6},
            "treasury": 100, "population": 100, "military_supply": 80,
            "civil_morale": 60, "military_morale": 70, "court_prestige": 75,
            "factions": [], "active_events": [], "history_log": [],
            "decree_count": 5, "event_cooldowns": {}, "regions": [],
        }
        if include_ministers:
            data["ministers"] = [m.model_dump() for m in INITIAL_MINISTERS]
        elif ministers_val is not None:
            data["ministers"] = ministers_val
        return data

    def test_missing_ministers_filled(self):
        data = self._old_save()
        notes = _migrate_save(data)
        assert "ministers" in data
        assert len(data["ministers"]) == len(INITIAL_MINISTERS)

    def test_corrupt_ministers_reset(self):
        data = self._old_save(ministers_val=[{"bad": True}])
        notes = _migrate_save(data)
        assert len(data["ministers"]) == len(INITIAL_MINISTERS)

    def test_valid_ministers_preserved(self):
        data = self._old_save(include_ministers=True)
        data["time"]["era_name"] = "崇祯"
        data["time"]["era_year"] = 3
        data["resolved_script_ids"] = []
        notes = _migrate_save(data)
        assert len(data["ministers"]) == len(INITIAL_MINISTERS)
        assert not any("大臣" in n for n in notes)

    def test_old_time_preserved(self):
        data = self._old_save(include_ministers=True)
        original_year = data["time"]["year"]
        _migrate_save(data)
        assert data["time"]["year"] == original_year

    def test_idempotent(self):
        data = self._old_save()
        _migrate_save(data)
        snap1 = copy.deepcopy(data)
        _migrate_save(data)
        assert data == snap1

    def test_small_roster_migration_expands(self):
        small = [m.model_dump() for m in INITIAL_MINISTERS[:3]]
        data = self._old_save(ministers_val=small)
        data["time"]["year"] = 1627
        data["time"]["month"] = 8
        notes = _migrate_save(data)
        assert len(data["ministers"]) >= 100, f"Expected >=100, got {len(data['ministers'])}"
        assert any("已扩充大臣至100+人" in n for n in notes)
        names = [m["name"] for m in data["ministers"]]
        assert len(names) == len(set(names)), "Duplicate names after migration"

    def test_small_roster_migration_preserves_existing(self):
        small = [m.model_dump() for m in INITIAL_MINISTERS[:5]]
        data = self._old_save(ministers_val=small)
        data["time"]["year"] = 1627
        data["time"]["month"] = 8
        _migrate_save(data)
        expanded_names = {m["name"] for m in data["ministers"]}
        for orig in small:
            assert orig["name"] in expanded_names
