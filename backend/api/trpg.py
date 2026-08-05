"""跑团引擎 API（阶段B）：角色卡查询 / 玩家行动检定与叙事。

- GET  /api/trpg/character  玩家与关键人物角色卡（含成长记录）。
- POST /api/trpg/act        玩家行动 → D100 检定 → AI主持人叙事 + 分支选项。

与治理引擎（engine/）平级、互不侵入；治理阶段仍可调用 /act 作辅助检定。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from models.game import HistoryEntry
from models.trpg import ATTR_KEYS, PLAYER_NAME, ActRequest, SKILL_ATTR_MAP
from trpg import chapter as chapter_mod
from trpg import character as character_mod
from trpg import dice as dice_mod
from trpg import gm as gm_mod
from .state import _get_provider, _get_state, _lock, _set_state

trpg_router = APIRouter(prefix="/api/trpg")
logger = logging.getLogger(__name__)

# /act 的叙事上下文：最近 N 条跑团历史摘要（与 gm.RECENT_NARRATIVE_WINDOW 对齐）
TRPG_HISTORY_TYPE = "trpg_act"


def _resolve_attr(req: ActRequest) -> str:
    """检定属性推断：显式 attr 优先 → 技能映射 → 兜底"胆略"。"""
    if req.attr and req.attr.strip() in ATTR_KEYS:
        return req.attr.strip()
    if req.skill:
        mapped = SKILL_ATTR_MAP.get(req.skill.strip())
        if mapped:
            return mapped
    return "胆略"


def _recent_trpg_narratives(state) -> list[str]:
    narratives = [
        entry.narrative
        for entry in state.history_log
        if entry.decree_type == TRPG_HISTORY_TYPE and entry.narrative
    ]
    return narratives[-gm_mod.RECENT_NARRATIVE_WINDOW:]


# ── GET /api/trpg/character ─────────────────────────────

@trpg_router.get("/character")
async def get_character():
    async with _lock:
        state = _get_state()
        sheets = character_mod.ensure_sheets(state)
        player = sheets.get(PLAYER_NAME)
        key_figures = [
            sheet.model_dump()
            for name, sheet in sheets.items()
            if name != PLAYER_NAME
        ]
        return {
            "player": player.model_dump() if player else None,
            "key_figures": key_figures,
            "growth_log": [entry.model_dump() for entry in state.growth_log],
            "phase": state.phase,
            "chapter": state.chapter,
            "chapter_title": chapter_mod.chapter_title(state.chapter),
        }


# ── POST /api/trpg/act ──────────────────────────────────

@trpg_router.post("/act")
async def act(req: ActRequest):
    async with _lock:
        state = _get_state().model_copy(deep=True)
        sheets = character_mod.ensure_sheets(state)
        sheet = sheets.get(PLAYER_NAME)

        attr_name = _resolve_attr(req)
        skill_name = req.skill.strip() if req.skill else None

        # 1. D100 检定
        roll = dice_mod.perform_check(sheet, attr_name, skill_name, req.difficulty)

        # 2. 成长：叙事回合约 1-2 技能点（自动折算成长点并投入检定属性）
        points = character_mod.narrative_turn_points(roll.tier)
        growth = character_mod.award_skill_points(
            state, PLAYER_NAME, points, "叙事回合", attr_name,
        )

        # 3. 篇章节奏与 1360 兜底钩子（governance 冻结时不记录回合）
        frozen = chapter_mod.is_frozen(state)
        if not frozen:
            chapter_mod.record_turn(state)
        convergence = chapter_mod.check_convergence_hook(state)

        # 4. AI 主持人生成叙事与分支选项（AI 不可用/解析失败 → 规则回退）
        result = await gm_mod.generate_turn(
            _get_provider(),
            state=state,
            sheet=sheet,
            action_text=req.action_text,
            roll=roll,
            chapter_title=chapter_mod.chapter_title(state.chapter),
            recent_narratives=_recent_trpg_narratives(_get_state()),
        )

        # 5. 历史记录（供滚动窗口与存档回放）
        state.history_log.append(HistoryEntry(
            year=state.time.year,
            month=state.time.month,
            decree_type=TRPG_HISTORY_TYPE,
            decree_desc=req.action_text.strip(),
            narrative=result["narrative"],
        ))

        _set_state(state)

        return {
            "roll": roll.model_dump(),
            "narrative": result["narrative"],
            "options": result["options"],
            "state_changes": result["state_changes"],
            "source": result["source"],
            "phase": state.phase,
            "chapter": state.chapter,
            "chapter_title": chapter_mod.chapter_title(state.chapter),
            "chapter_turns": state.chapter_turns,
            "pacing": chapter_mod.pacing_status(state.chapter_turns),
            "frozen": frozen,
            "growth": growth.model_dump() if growth else None,
            "convergence_hook": convergence,
            "time": {
                "year": state.time.year,
                "month": state.time.month,
                "era_name": state.time.era_name,
                "era_year": state.time.era_year,
            },
        }
