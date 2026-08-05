from db.saves import _migrate_save
from models.game import INITIAL_MINISTERS


def _old_save_data(year: int, regions=None, include_ministers=False) -> dict:
    data = {
        "time": {"year": year, "month": 6},
        "national_treasury": 50, "imperial_treasury": 30, "grain": 20,
        "population": 15000, "military_strength": 80,
        "civil_morale": 60, "military_morale": 70, "court_prestige": 75,
        "factions": [], "active_events": [], "history_log": [],
        "decree_count": 5, "event_cooldowns": {},
        "regions": regions or [],
    }
    if include_ministers:
        data["ministers"] = [m.model_dump() for m in INITIAL_MINISTERS]
    return data


class TestYearMigration:
    def test_relative_year_converts(self):
        data = _old_save_data(1)
        _migrate_save(data)
        assert data["time"]["year"] == 1357  # 1 + 1356

    def test_relative_year_zero(self):
        data = _old_save_data(0)
        _migrate_save(data)
        assert data["time"]["year"] == 1356

    def test_relative_year_12(self):
        data = _old_save_data(12)
        _migrate_save(data)
        assert data["time"]["year"] == 1368  # 12 + 1356

    def test_absolute_year_1356_preserved(self):
        data = _old_save_data(1356)
        _migrate_save(data)
        assert data["time"]["year"] == 1356

    def test_absolute_year_1368_preserved(self):
        data = _old_save_data(1368)
        _migrate_save(data)
        assert data["time"]["year"] == 1368

    def test_absolute_year_1340_preserved(self):
        data = _old_save_data(1340)
        _migrate_save(data)
        assert data["time"]["year"] == 1340

    def test_boundary_99_converts(self):
        data = _old_save_data(99)
        _migrate_save(data)
        assert data["time"]["year"] == 99 + 1356

    def test_boundary_100_no_convert(self):
        """year=100 is NOT < 100, should stay 100 (not added to 1356)."""
        data = _old_save_data(100)
        _migrate_save(data)
        assert data["time"]["year"] == 100  # stays as-is, not treated as relative

    def test_migration_flag_for_relative(self):
        data = _old_save_data(5)
        notes = _migrate_save(data)
        assert len(notes) > 0

    def test_no_migration_for_absolute_with_era(self):
        data = _old_save_data(1360, include_ministers=True)
        data["time"]["era_name"] = "至正"
        data["time"]["era_year"] = 20
        data["phase"] = "governance"
        data["resolved_script_ids"] = []
        notes = _migrate_save(data)
        assert len(notes) == 0


class TestEraMigration:
    def test_era_added_tianli(self):
        data = _old_save_data(1328)
        _migrate_save(data)
        assert data["time"]["era_name"] == "天历"
        assert data["time"]["era_year"] == 1  # 1328 - 1328 + 1

    def test_era_added_zhizheng(self):
        data = _old_save_data(1360)
        _migrate_save(data)
        assert data["time"]["era_name"] == "至正"
        assert data["time"]["era_year"] == 20  # 1360 - 1341 + 1


class TestRegionMigration:
    def test_region_fields_added(self):
        region = {
            "name": "京畿", "stability": 80, "garrison": 50000,
            "control": "朝廷", "threat": "none", "tax_contribution": "medium",
        }
        data = _old_save_data(1627, regions=[region])
        notes = _migrate_save(data)
        r = data["regions"][0]
        assert len(notes) > 0
        assert "civil_morale" in r
        assert "rebellion_risk" in r
        assert "tax_rate" in r
        assert "tax_collected" in r
        assert "disaster_level" in r

    def test_civil_morale_from_stability(self):
        region = {"name": "t", "stability": 60, "garrison": 1000,
                  "control": "朝廷", "threat": "none", "tax_contribution": "medium"}
        data = _old_save_data(1627, regions=[region])
        _migrate_save(data)
        assert data["regions"][0]["civil_morale"] == 55  # stab - 5

    def test_rebellion_risk_threat_none(self):
        region = {"name": "t", "stability": 80, "garrison": 1000,
                  "control": "朝廷", "threat": "none", "tax_contribution": "medium"}
        data = _old_save_data(1627, regions=[region])
        _migrate_save(data)
        assert data["regions"][0]["rebellion_risk"] == 10

    def test_rebellion_risk_with_threat(self):
        region = {"name": "t", "stability": 30, "garrison": 1000,
                  "control": "朝廷", "threat": "元军", "tax_contribution": "low"}
        data = _old_save_data(1627, regions=[region])
        _migrate_save(data)
        assert data["regions"][0]["rebellion_risk"] == 70  # 100 - 30

    def test_tax_rate_by_contribution(self):
        for contrib, expected in [("low", 0.3), ("medium", 0.5), ("high", 0.8)]:
            region = {"name": "t", "stability": 50, "garrison": 1000,
                      "control": "朝廷", "threat": "none", "tax_contribution": contrib}
            data = _old_save_data(1627, regions=[region])
            _migrate_save(data)
            assert data["regions"][0]["tax_rate"] == expected

    def test_disaster_level_by_threat(self):
        for threat, expected in [("none", 0), ("元军", 40), ("汉军", 45), ("民变", 60), ("土司", 30)]:
            region = {"name": "t", "stability": 50, "garrison": 1000,
                      "control": "朝廷", "threat": threat, "tax_contribution": "medium"}
            data = _old_save_data(1627, regions=[region])
            _migrate_save(data)
            assert data["regions"][0]["disaster_level"] == expected

    def test_existing_fields_not_overwritten(self):
        region = {"name": "t", "stability": 50, "garrison": 1000,
                  "control": "朝廷", "threat": "none", "tax_contribution": "medium",
                  "civil_morale": 99, "rebellion_risk": 1, "tax_rate": 0.77,
                  "tax_collected": 42, "disaster_level": 5}
        data = _old_save_data(1627, regions=[region])
        _migrate_save(data)
        r = data["regions"][0]
        assert r["civil_morale"] == 99
        assert r["rebellion_risk"] == 1
        assert r["tax_rate"] == 0.77
        assert r["tax_collected"] == 42
        assert r["disaster_level"] == 5
