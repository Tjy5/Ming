from ai.prompts import build_minister_dialogue_prompt
from models.game import create_initial_state


def test_dialogue_prompt_includes_personality_and_biography_fields():
    state = create_initial_state()
    minister = next(m.model_copy(deep=True) for m in state.ministers if m.status.value == "active")
    minister.personality_tags = ["刚直", "谨慎"]
    minister.historical_note = "时人称其守正。"
    minister.biography = "历任地方与中枢职务，重视财政整饬。"
    minister.major_contributions = ["整顿盐政", "清理积欠军饷"]

    prompt = build_minister_dialogue_prompt(
        minister=minister,
        message="你怎么看财政？",
        game_state=state,
        conversation_history=[],
    )

    assert "性格：刚直、谨慎" in prompt
    assert "史实备注：时人称其守正。" in prompt
    assert "人物生平：历任地方与中枢职务，重视财政整饬。" in prompt
    assert "主要事功：整顿盐政；清理积欠军饷" in prompt
