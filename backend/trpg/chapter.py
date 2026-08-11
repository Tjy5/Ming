"""人生篇章推进：读 timeline.json chapters，驱动章节切换与年份跳转。

篇章制（父 design 第 1.1 节）：
- 农家子(childhood) → 僧旅飘零(monk_wanderer) → 投军奋起(enlistment) → 割据江东(warlord)。
- 每章 3-8 个叙事回合；关键事件完成 → 下一章 + 年份跳转 + 过渡摘要。
- **phase 切换截断处理**：进入 governance 后冻结篇章推进——warlord 章
  保留为当前章但不再驱动叙事回合（切换与收束逻辑联通归阶段D）。
- **1360 兜底钩子**：至正二十年仍未完成"攻占应天" → 返回收束抉择钩子
  信息（收束逻辑联通归阶段D，本阶段只留钩子）。
"""
from __future__ import annotations

import copy
import json
import logging
import threading
from pathlib import Path

from models.game import GameState

logger = logging.getLogger(__name__)

_TIMELINE_JSON = Path(__file__).resolve().parents[1] / "data" / "yuanming" / "timeline.json"

# 每章叙事回合数区间（GM 节奏约束）
CHAPTER_MIN_TURNS = 3
CHAPTER_MAX_TURNS = 8

_TIMELINE_CACHE: dict | None = None
_TIMELINE_MTIME_NS: int | None = None
_TIMELINE_LOCK = threading.RLock()


# ── 时间线数据 ───────────────────────────────────────────

def load_timeline(*, refresh: bool = False) -> dict:
    """读取 timeline.json（按 mtime 缓存，返回深拷贝）。"""
    global _TIMELINE_CACHE, _TIMELINE_MTIME_NS
    with _TIMELINE_LOCK:
        mtime_ns = _TIMELINE_JSON.stat().st_mtime_ns
        if refresh or _TIMELINE_CACHE is None or mtime_ns != _TIMELINE_MTIME_NS:
            raw = json.loads(_TIMELINE_JSON.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("timeline.json must be a JSON object")
            _TIMELINE_CACHE = raw
            _TIMELINE_MTIME_NS = mtime_ns
        return copy.deepcopy(_TIMELINE_CACHE)


def get_chapters() -> list[dict]:
    return load_timeline().get("chapters", [])


def get_chapter(chapter_id: str) -> dict | None:
    return next((c for c in get_chapters() if c.get("id") == chapter_id), None)


def chapter_title(chapter_id: str) -> str:
    chapter = get_chapter(chapter_id)
    return chapter.get("title", chapter_id) if chapter else chapter_id


def get_phase_switch() -> dict:
    return load_timeline().get("phase_switch", {})


def get_milestones(chapter_id: str | None = None) -> list[dict]:
    milestones = load_timeline().get("milestones", [])
    if chapter_id is None:
        return milestones
    return [m for m in milestones if m.get("chapter") == chapter_id]


# ── 篇章推进 ─────────────────────────────────────────────

def is_frozen(state: GameState) -> bool:
    """phase 截断：进入 governance 后篇章推进冻结（warlord 章保留不驱动叙事）。"""
    return state.phase != "life_story"


def _chapter_index(chapter_id: str) -> int | None:
    chapters = get_chapters()
    for idx, chapter in enumerate(chapters):
        if chapter.get("id") == chapter_id:
            return idx
    return None


def advance_chapter(state: GameState) -> dict | None:
    """推进到下一章：跳转年份并返回过渡摘要。

    冻结（governance）/ 已是最后一章 / 未知篇章 → 返回 None。
    """
    if is_frozen(state):
        return None
    chapters = get_chapters()
    idx = _chapter_index(state.chapter)
    if idx is None or idx + 1 >= len(chapters):
        return None

    current = chapters[idx]
    nxt = chapters[idx + 1]
    state.chapter = nxt["id"]
    state.chapter_turns = 0
    # Compatibility adapter only.  The later activity/checkpoint migration will
    # replace chapter date anchors with elapsed-time settlements.
    from engine.calendar import set_game_time_projection
    set_game_time_projection(
        state.time,
        year=int(nxt["start_year"]),
        month=1,
    )

    start_milestone = next(
        (m for m in get_milestones(nxt["id"])),
        None,
    )
    hint = f"{start_milestone['summary']}" if start_milestone else ""
    summary = (
        f"岁月流转，自《{current.get('title', '')}》步入《{nxt.get('title', '')}》。"
        f"{state.time.year}年，新的篇章开启。"
        + (f"{hint}" if hint else "")
    )
    return {
        "from_chapter": current.get("id"),
        "to_chapter": nxt.get("id"),
        "year": state.time.year,
        "summary": summary,
    }


def complete_key_event(state: GameState, milestone_id: str) -> dict | None:
    """完成关键事件：标记里程碑；若为该章最后关键事件 → 推进下一章。

    里程碑带 phase_switch 标记时（如 yingtian-founding），结果中返回
    phase_switch=True 供阶段D触发切换；本阶段不改 phase。
    """
    timeline = load_timeline()
    milestone = next(
        (m for m in timeline.get("milestones", []) if m.get("id") == milestone_id),
        None,
    )
    if milestone is None:
        return None
    state.resolved_script_ids.add(milestone_id)
    result: dict = {
        "milestone": milestone_id,
        "title": milestone.get("title", ""),
        "phase_switch": bool(milestone.get("phase_switch")),
        "transition": None,
    }
    # 该章最后一个关键事件完成 → 进入下一章（冻结时 advance_chapter 返回 None）
    if milestone.get("chapter") == state.chapter:
        chapter_milestones = get_milestones(state.chapter)
        if chapter_milestones and chapter_milestones[-1].get("id") == milestone_id:
            result["transition"] = advance_chapter(state)
    return result


# ── 回合节奏 ─────────────────────────────────────────────

def record_turn(state: GameState) -> int:
    """记录一个叙事回合，返回当前章累计回合数。"""
    state.chapter_turns += 1
    return state.chapter_turns


def pacing_status(turns_taken: int) -> dict:
    """每章 3-8 回合的节奏提示（供 GM/阶段D 决策）。"""
    return {
        "turns_taken": turns_taken,
        "min_turns": CHAPTER_MIN_TURNS,
        "max_turns": CHAPTER_MAX_TURNS,
        "may_advance": turns_taken >= CHAPTER_MIN_TURNS,
        "must_advance": turns_taken >= CHAPTER_MAX_TURNS,
    }


# ── 1360 兜底钩子 ────────────────────────────────────────

def check_convergence_hook(state: GameState) -> dict | None:
    """兜底：fallback_year(1360) 仍未完成攻占应天 → 返回收束钩子信息。

    收束抉择事件的生成与强制切换归阶段D；本阶段仅提供探测钩子。
    """
    if is_frozen(state):
        return None
    phase_switch = get_phase_switch()
    fallback_year = int(phase_switch.get("fallback_year", 1360))
    if state.time.year < fallback_year:
        return None
    milestone_id = phase_switch.get("milestone")
    if not milestone_id or milestone_id in state.resolved_script_ids:
        return None
    return {
        "hook": "convergence",
        "milestone": milestone_id,
        "fallback_year": fallback_year,
        "message": (
            f"已至{fallback_year}年而仍未克应天，主持人将发起收束抉择事件，"
            "强制剧情走向收束（收束逻辑由阶段D接管）。"
        ),
    }
