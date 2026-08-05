import json

from ai.provider import extract_json_object_text, parse_debate_response
from models.enums import DecreeType, PersonnelAction
from models.game import create_initial_state


def _ministers():
    state = create_initial_state()
    assert len(state.ministers) >= 2
    return state.ministers[0], state.ministers[1]


def test_extract_json_object_text_unwraps_fenced_json():
    raw = "```json\n{\"a\":1,\"b\":2}\n```"
    extracted = extract_json_object_text(raw)
    assert json.loads(extracted) == {"a": 1, "b": 2}


def test_parse_debate_response_coerces_policy_like_options():
    a, b = _ministers()
    payload = {
        "debate_text": "甲乙围绕赋税辩论。",
        "minister_a_position": "主张加税",
        "minister_b_position": "主张养民",
        "option_a": {
            "type": "policy",
            "target": "taxation",
            "sub_action": "increase_heavy_tax",
        },
        "option_b": {
            "type": "policy",
            "target": "agriculture",
            "sub_action": "promote_farming",
        },
        "keywords": ["赋税", "民生"],
    }

    result = parse_debate_response(payload, a, b)
    assert result is not None
    assert result.option_a.type == DecreeType.TAX_INCREASE
    assert result.option_b.type == DecreeType.TAX_DECREASE


def test_parse_debate_response_coerces_personnel_sub_action():
    a, b = _ministers()
    payload = {
        "debate_text": "甲乙围绕人事任免辩论。",
        "minister_a_position": "主张罢免",
        "minister_b_position": "主张任命",
        "option_a": {
            "type": "personnel",
            "target": "杨宪",
            "sub_action": "remove_official",
        },
        "option_b": {
            "type": "personnel",
            "target": "刘基",
            "sub_action": "appoint_new",
        },
        "keywords": ["人事", "任免"],
    }

    result = parse_debate_response(payload, a, b)
    assert result is not None
    assert result.option_a.type == DecreeType.PERSONNEL
    assert result.option_b.type == DecreeType.PERSONNEL
    assert result.option_a.sub_action == PersonnelAction.DISMISS
    assert result.option_b.sub_action == PersonnelAction.APPOINT
