from __future__ import annotations

from models.enums import MinisterStatus
from models.game import GameState
from engine.scripts import ScriptEvent

_VACANCY_HINTS = ("空缺", "继任", "补缺", "替补", "vacancy")


def _event_text_blob(event: ScriptEvent) -> str:
    parts = [event.title, event.rich_description]
    for choice in event.choices:
        parts.append(choice.label)
        parts.append(choice.description)
    return " ".join(part for part in parts if part).strip()


def _has_vacancy_fallback(text: str) -> bool:
    lower_text = text.lower()
    return any(hint in text or hint in lower_text for hint in _VACANCY_HINTS)


def _condition_accepts_removed_names(condition_spec: dict | None, removed_names: set[str]) -> bool:
    if not isinstance(condition_spec, dict) or not removed_names:
        return False
    node_type = condition_spec.get("type")
    if node_type == "minister_removed":
        name = condition_spec.get("name")
        return isinstance(name, str) and name in removed_names
    if node_type == "and":
        children = condition_spec.get("conditions")
        if isinstance(children, list):
            return any(
                _condition_accepts_removed_names(child, removed_names)
                for child in children
                if isinstance(child, dict)
            )
    return False


def _relevance_score(state: GameState, event: ScriptEvent) -> tuple[int, int, str]:
    # Deterministic ranking for same state+candidates.
    score = 0
    if event.is_blocking:
        score += 100
    score += len(event.choices) * 5
    if event.condition_spec:
        score += 3
    score += min(len(event.rich_description) // 120, 5)
    # Prefer events involving currently active ministers over idle/removed references.
    active_names = {
        m.name for m in state.ministers
        if m.status in {MinisterStatus.ACTIVE, MinisterStatus.IDLE}
    }
    text = _event_text_blob(event)
    score += sum(1 for name in active_names if name and name in text)
    return score, len(event.title), event.script_id


def select_script_trigger_decisions(
    state: GameState,
    candidates: list[ScriptEvent],
) -> dict[str, tuple[bool, str]]:
    decisions: dict[str, tuple[bool, str]] = {}
    removed_names = {
        m.name for m in state.ministers
        if m.status == MinisterStatus.REMOVED
    }

    for event in candidates:
        text = _event_text_blob(event)
        mentioned_removed = [name for name in removed_names if name and name in text]
        if (
            mentioned_removed
            and not _has_vacancy_fallback(text)
            and not _condition_accepts_removed_names(event.condition_spec, set(mentioned_removed))
        ):
            decisions[event.script_id] = (
                False,
                f"关键人物已不在朝：{'、'.join(sorted(mentioned_removed))}",
            )
            continue

        decisions[event.script_id] = (True, "规则通过且与当前局势相关")

    # Conflict handling: if multiple blocking events are triggerable, keep the top-ranked one.
    triggerable_blocking = [
        event for event in candidates
        if event.is_blocking and decisions.get(event.script_id, (False, ""))[0]
    ]
    if len(triggerable_blocking) > 1:
        selected = max(triggerable_blocking, key=lambda event: _relevance_score(state, event))
        for event in triggerable_blocking:
            if event.script_id == selected.script_id:
                continue
            decisions[event.script_id] = (False, f"与同月更紧急事件冲突，顺延处理：{selected.title}")

    return decisions
