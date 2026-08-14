from engine.core import apply_region_impact, validate_ai_effects, validate_target
from models.enums import DecreeType
from models.game import StructuredDecree, create_initial_state


HENAN_JIANGBEI_MEMBERS = {"两淮", "应天", "太平", "镇江", "平江"}


def test_historical_division_is_a_valid_relief_target_and_legacy_names_remain_valid():
    state = create_initial_state()

    assert validate_target(
        StructuredDecree(type=DecreeType.DISASTER_RELIEF, target="河南江北行省"),
        state,
    ) is None
    assert validate_target(
        StructuredDecree(type=DecreeType.DISASTER_RELIEF, target="应天"),
        state,
    ) is None
    assert validate_target(
        StructuredDecree(type=DecreeType.DISASTER_RELIEF, target="江西行省"),
        state,
    ) is not None


def test_relief_for_historical_division_broadcasts_to_all_bound_legacy_regions():
    state = create_initial_state()
    before = {region.name: region.model_copy(deep=True) for region in state.regions}
    decree = StructuredDecree(type=DecreeType.DISASTER_RELIEF, target="河南江北行省")

    apply_region_impact(state, decree, {})

    for region in state.regions:
        if region.name in HENAN_JIANGBEI_MEMBERS:
            assert region.stability == before[region.name].stability + 22
            assert region.civil_morale == before[region.name].civil_morale + 10
            assert region.disaster_level == before[region.name].disaster_level - 18
            assert region.rebellion_risk == before[region.name].rebellion_risk - 8
        else:
            assert region == before[region.name]


def test_freeform_division_effect_expands_without_overwriting_explicit_member_effect():
    state = create_initial_state()
    effects = {
        "region.河南江北行省.stability": 5,
        "region.应天.stability": 2,
    }

    valid = validate_ai_effects(effects, state)

    assert "region.河南江北行省.stability" not in valid
    assert valid["region.应天.stability"] == 2
    assert {
        path.removeprefix("region.").removesuffix(".stability")
        for path in valid
    } == HENAN_JIANGBEI_MEMBERS
    assert all(
        value == 5
        for path, value in valid.items()
        if path != "region.应天.stability"
    )
