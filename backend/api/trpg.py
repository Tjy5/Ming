"""跑团引擎 API（阶段B）：角色卡查询 / 玩家行动检定与叙事。

- GET  /api/trpg/character  玩家与关键人物角色卡（含成长记录）。
- POST /api/trpg/act        玩家行动 → D100 检定 → AI主持人叙事 + 分支选项。
- POST /api/trpg/milestones/{milestone_id}/complete
                            完成关键事件：成长奖励 + 章推进；
                            带 phase_switch 标记时翻转 phase（阶段D）。

与治理引擎（engine/）平级、互不侵入；治理阶段仍可调用 /act 作辅助检定。
"""
from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, HTTPException

from db import narrative_memory
from db import saves as db_saves
from models.game import ErrorResponse, HistoryEntry
from models.settlement import ResultTier
from models.trpg import ATTR_KEYS, PLAYER_NAME, ActRequest, ConvergeRequest, SKILL_ATTR_MAP
from models.world_state import RollRecord, VisibleRollModifier
from trpg import chapter as chapter_mod
from trpg import character as character_mod
from trpg import dice as dice_mod
from trpg import gm as gm_mod
from trpg import writeback as writeback_mod
from .narrative_routes import generate_committed_narrative
from .state import _ensure_world_head, _get_provider, _get_state, _lock, _settle_state

trpg_router = APIRouter(prefix="/api/trpg")
logger = logging.getLogger(__name__)

# /act 的叙事上下文：最近 N 条跑团历史摘要（与 gm.RECENT_NARRATIVE_WINDOW 对齐）
TRPG_HISTORY_TYPE = "trpg_act"

# 1360 收束抉择选项：check_convergence_hook 非空时附加到 /act 响应 options。
# convergence 标记（accept/refuse）供前端路由到 POST /api/trpg/converge。
CONVERGENCE_OPTIONS: list[dict] = [
    {
        "option_id": "opt_converge_accept",
        "label": "接受招揽，归于治下",
        "description": "应天诸将相迎，就此归附，以治理之责承续霸业。",
        "convergence": "accept",
    },
    {
        "option_id": "opt_converge_refuse",
        "label": "继续流窜，拒不归降",
        "description": "拒绝归附，转入流亡困局，在当前世界中另寻生路。",
        "convergence": "refuse",
    },
]


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
    metadata = state.world_metadata
    if metadata.game_id is None or metadata.branch_id is None or metadata.version_id is None:
        return []
    records = narrative_memory.list_visible_memories(
        game_id=metadata.game_id,
        branch_id=metadata.branch_id,
        version_id=metadata.version_id,
        mode="trpg",
        topic_id="trpg",
        current_phase=state.phase,
        current_chapter=state.chapter,
        limit=gm_mod.RECENT_NARRATIVE_WINDOW * 2,
    )
    return [
        record.content for record in records if record.role == "assistant"
    ][-gm_mod.RECENT_NARRATIVE_WINDOW:]


def _settlement_tier(roll_tier: str) -> ResultTier:
    return "success" if roll_tier in {"critical_success", "success"} else "failure"


def _roll_record(*, state, sheet, action_text: str, roll) -> RollRecord:
    modifiers = [
        VisibleRollModifier(
            name=f"{roll.attr_name or '属性'}半值",
            value=sheet.attr(roll.attr_name or "") // 2,
            source_fact=f"character:{sheet.name}:attribute:{roll.attr_name or 'unknown'}",
        ),
    ]
    skill_value = sheet.skill(roll.skill_name)
    if skill_value is not None:
        modifiers.append(VisibleRollModifier(
            name=f"{roll.skill_name}半值",
            value=skill_value // 2,
            source_fact=f"character:{sheet.name}:skill:{roll.skill_name}",
        ))
    modifiers.append(VisibleRollModifier(
        name="难度修正",
        value=roll.dc,
        source_fact=f"trpg:difficulty:{roll.dc:+d}",
    ))
    identity = json.dumps(
        {
            "version_id": str(state.world_metadata.version_id),
            "action_text": action_text.strip(),
            "roll": roll.model_dump(mode="json"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return RollRecord(
        roll_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        protocol_version="trpg-d100-v1",
        raw_d100=roll.roll,
        target_value=roll.target,
        result_tier=roll.tier,
        modifiers=modifiers,
        uncertainty_reasons=["volatile_environment"],
        fact_references=[
            f"version:{state.world_metadata.version_id}",
            f"trpg:target:{roll.target}",
        ],
        checkpoint_slot=f"trpg:{state.chapter}",
    )


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
        current_state, _current_ref = _ensure_world_head()
        state = current_state.model_copy(deep=True)
        sheets = character_mod.ensure_sheets(state)
        sheet = sheets.get(PLAYER_NAME)

        attr_name = _resolve_attr(req)
        skill_name = req.skill.strip() if req.skill else None

        # 篇章 DC 曲线（design 第 4.1 节）：difficulty 未显式指定（None/常规/
        # normal）时按当前章默认难度；显式指定（简易/困难/极难等）尊重原值
        difficulty = req.difficulty
        if (difficulty or "").strip() in ("", "常规", "normal"):
            difficulty = dice_mod.chapter_default_difficulty(state.chapter)

        # 1. D100 检定
        roll = dice_mod.perform_check(sheet, attr_name, skill_name, difficulty)

        # 2. 成长：叙事回合约 1-2 技能点（自动折算成长点并投入检定属性）
        points = character_mod.narrative_turn_points(roll.tier)
        growth = character_mod.award_skill_points(
            state, PLAYER_NAME, points, "叙事回合", attr_name,
        )

        # 3. 篇章节奏与 1360 兜底钩子（governance 冻结时不记录回合）
        frozen = chapter_mod.is_frozen(state)
        if not frozen:
            chapter_mod.record_turn(state)
        convergence = chapter_mod.check_convergence_hook(
            state,
            include_early_candidates=bool(req.allow_early_candidate),
        )

        # 4. AI 主持人生成叙事与分支选项（AI 不可用/解析失败 → 规则回退）
        result = await gm_mod.generate_turn(
            _get_provider(),
            state=state,
            sheet=sheet,
            action_text=req.action_text,
            roll=roll,
            chapter_title=chapter_mod.chapter_title(state.chapter),
            recent_narratives=_recent_trpg_narratives(current_state),
        )

        # 4.5 1360 收束抉择：convergence_hook 非空 → 本轮附加收束选项
        # （convergence 标记供前端路由到 /converge；仅本次响应出现）
        options = result["options"]
        if convergence is not None:
            options = options + CONVERGENCE_OPTIONS

        # 4.6 GM state_changes 应用层（design 第 3.2 节）：WRITABLE_FIELDS
        # 白名单校验后应用，非法字段丢弃并记日志；结果随响应返回（向后兼容）
        state_changes_result = writeback_mod.apply_state_changes(state, result["state_changes"])

        # 5. 历史记录（供滚动窗口与存档回放）
        state.history_log.append(HistoryEntry(
            year=state.time.year,
            month=state.time.month,
            decree_type=TRPG_HISTORY_TYPE,
            decree_desc=req.action_text.strip(),
            # The GM candidate may guide structured options/state changes, but
            # only the post-commit canonical artifact is player-visible.
            narrative="",
        ))

        public_roll = _roll_record(
            state=current_state,
            sheet=sheet,
            action_text=req.action_text,
            roll=roll,
        )
        state, settlement_result = await _settle_state(
            state,
            action_kind="trpg_act",
            raw_text=req.action_text,
            result_tier=_settlement_tier(roll.tier),
            key_factors=[
                f"D100 {roll.roll} / 目标 {roll.target} / {roll.tier}",
            ],
            rolls=[public_roll],
        )
        narrative_result = await generate_committed_narrative(
            state=state,
            facts=settlement_result.facts,
            path_id="trpg_gm_action",
            topic_id="trpg",
            action_text=req.action_text,
            reuse_current=settlement_result.replayed,
        )

        return {
            "roll": roll.model_dump(),
            "narrative": narrative_result.text,
            "narrative_status": narrative_result.narrative_status,
            "narrative_path_id": narrative_result.path_id,
            "settlement_id": narrative_result.settlement_id,
            "context_version_id": narrative_result.context_version_id,
            "narrative_artifact_id": narrative_result.artifact_id,
            "narrative_request_id": narrative_result.request_id,
            "narrative_progress": narrative_result.progress_stages,
            "options": options,
            "state_changes": result["state_changes"],
            "state_changes_result": state_changes_result,
            "source": result["source"],
            # option_id（design 第 5.1 节）：确定性选择的双通道，随响应回显
            # 供 e2e/脚本化断言；不校验匹配（历史选项无状态存储），不匹配忽略不报错
            "option_id": req.option_id,
            "phase": state.phase,
            "chapter": state.chapter,
            "chapter_title": chapter_mod.chapter_title(state.chapter),
            "chapter_turns": state.chapter_turns,
            "pacing": chapter_mod.pacing_status(state.chapter_turns),
            "frozen": frozen,
            "growth": growth.model_dump() if growth else None,
            "convergence_hook": convergence,
            "time": state.time.model_dump(mode="json"),
        }


# ── POST /api/trpg/milestones/{milestone_id}/complete ──

@trpg_router.post("/milestones/{milestone_id}/complete")
async def complete_milestone(milestone_id: str):
    """完成关键事件（里程碑）：成长奖励 + 章推进。

    - 已解析里程碑 → 409（milestone_already_resolved，单次史实事件不可重复完成）。
    - 未知里程碑 → 404（milestone_not_found）。
    - 里程碑日期仅作历史与显示提示，不改世界时钟；经过时间只能由统一
      action/activity settlement 推进。
    - 带 phase_switch 标记的里程碑（yingtian-founding）且 phase 尚未切换时：
      翻转 phase → to_phase（governance）、写存档快照（回滚点）、
      过渡叙事追加 history_log（decree_type=trpg_act）。
    - 进入 governance 后（is_frozen）里程碑仍可完成：不翻 phase、无异常。
    """
    async with _lock:
        state = _get_state().model_copy(deep=True)
        # 单次史实事件：已解析里程碑拒绝重复完成（409，防止重复成长奖励与时间回拨）
        if milestone_id in state.resolved_script_ids:
            raise HTTPException(409, detail=ErrorResponse(
                error_code="milestone_already_resolved",
                message=f"关键事件 {milestone_id} 已达成，不可重复完成",
            ).model_dump())
        character_mod.ensure_sheets(state)  # 同 /act：新档角色卡惰性初始化，成长奖励落卡
        result = character_mod.complete_key_event_with_growth(state, milestone_id)
        if result is None:
            raise HTTPException(404, detail=ErrorResponse(
                error_code="milestone_not_found",
                message=f"关键事件 {milestone_id} 不存在",
            ).model_dump())

        milestone = next(
            (m for m in chapter_mod.get_milestones() if m.get("id") == milestone_id),
            None,
        )

        # phase 翻转：仅 phase_switch 里程碑且未切换过时执行（幂等，governance 内不重复）
        switched = False
        if result.get("phase_switch"):
            to_phase = chapter_mod.get_phase_switch().get("to_phase", "governance")
            if state.phase != to_phase:
                state.phase = to_phase
                switched = True

        # 过渡叙事：阶段切换 → 引用 phase_switch.note；章推进 → 跳章摘要；否则里程碑摘要
        if switched:
            note = ""
            if milestone is not None:
                note = chapter_mod.get_phase_switch().get("note") or milestone.get("summary", "")
            narrative = f"【阶段切换】{result['title']}。{note}"
        elif result.get("transition"):
            narrative = result["transition"]["summary"]
        else:
            narrative = milestone.get("summary", "") if milestone else ""

        state.history_log.append(HistoryEntry(
            year=state.time.year,
            month=state.time.month,
            decree_type=TRPG_HISTORY_TYPE,
            decree_desc=f"关键事件:{result['title']}",
            narrative=narrative,
        ))

        state, settlement_result = await _settle_state(
            state,
            action_kind="trpg_milestone",
            raw_text=f"完成关键事件：{result['title']}",
        )

        # 主 settlement 成功后再写 best-effort 回滚快照，避免 AI duration
        # 或 commit 失败时留下并不存在于世界图中的幽灵状态。
        if switched:
            try:
                db_saves.save_game(
                    state,
                    name=f"阶段切换快照-{state.time.era_name}{state.time.era_year}年{state.time.month}月",
                )
            except Exception:
                logger.warning("阶段切换存档快照写入失败: %s", milestone_id, exc_info=True)

        return {
            "milestone": result["milestone"],
            "title": result["title"],
            "narrative": narrative,
            "transition": result.get("transition"),
            "growth": result.get("growth"),
            "phase": state.phase,
            "chapter": state.chapter,
            "chapter_title": chapter_mod.chapter_title(state.chapter),
            "chapter_turns": state.chapter_turns,
            "pacing": chapter_mod.pacing_status(state.chapter_turns),
            "frozen": chapter_mod.is_frozen(state),
            "time": state.time.model_dump(mode="json"),
            "settlement_id": settlement_result.facts.settlement_id,
            "context_version_id": settlement_result.version.version_id,
        }


# ── POST /api/trpg/converge ─────────────────────────────

@trpg_router.post("/converge")
async def converge(req: ConvergeRequest):
    """1360 收束抉择：接受招揽切换治理；拒绝归附则继续当前世界线。

    - 仅在 check_convergence_hook 激活时可用（life_story + 时间 ≥ fallback_year
      + yingtian-founding 未达成）；否则 409 convergence_not_pending。
    - 接受：yingtian-founding 写入 resolved_script_ids（409 闸口由此拦截其后的
      重复完成）、phase → governance、过渡叙事 history_log、存档快照（回滚点）。
      fallback_year 只用于叙事说明，不能改世界时钟。
    - 拒绝：进入资源匮乏、追兵压迫的流亡困局，但不得在没有已提交死亡
      settlement facts 时宣告主角死亡或终局；响应保持 game_over=null，玩家
      可继续自由行动并在后续结算中改变处境。
    """
    async with _lock:
        state = _get_state().model_copy(deep=True)
        hook = chapter_mod.check_convergence_hook(
            state,
            include_early_candidates=bool(req.allow_early_candidate),
        )
        if hook is None:
            raise HTTPException(409, detail=ErrorResponse(
                error_code="convergence_not_pending",
                message="当前无需收束抉择",
            ).model_dump())

        game_over = None
        converged_milestone = None
        if req.choice == "accept":
            phase_switch = chapter_mod.get_phase_switch()
            milestone_id = str(phase_switch.get("milestone") or "yingtian-founding")
            converged_milestone = milestone_id
            state.resolved_script_ids.add(milestone_id)
            state.phase = str(phase_switch.get("to_phase") or "governance")
            fallback_year = int(phase_switch.get("fallback_year", 1360))
            note = phase_switch.get("note") or hook.get("message") or ""
            narrative = (
                f"【收束·归附】{fallback_year}年，孤军漂泊终有定所——"
                f"应天诸将相迎，就此归附共图大业，以治理之责承续霸业。{note}"
            )
        else:
            narrative = (
                f"【收束·流亡】{state.time.year}年，{PLAYER_NAME}拒不归降，"
                "携残部转入江淮山野。兵微粮少、追兵未退，旧有道路愈发艰险；"
                "但当前世界线仍可继续，下一步须先求立足之地与可靠援手。"
            )

        state.history_log.append(HistoryEntry(
            year=state.time.year,
            month=state.time.month,
            decree_type=TRPG_HISTORY_TYPE,
            decree_desc="收束抉择:" + ("接受招揽" if req.choice == "accept" else "继续流窜"),
            narrative=narrative,
        ))

        state, settlement_result = await _settle_state(
            state,
            action_kind="trpg_convergence",
            raw_text="接受招揽" if req.choice == "accept" else "拒绝归降",
        )

        if req.choice == "accept":
            try:
                db_saves.save_game(
                    state,
                    name=f"收束切换快照-{state.time.era_name}{state.time.era_year}年{state.time.month}月",
                )
            except Exception:
                logger.warning("收束切换存档快照写入失败: %s", req.choice, exc_info=True)

        return {
            "choice": req.choice,
            "narrative": narrative,
            "game_over": game_over,
            "converged_milestone": converged_milestone,
            "phase": state.phase,
            "chapter": state.chapter,
            "chapter_title": chapter_mod.chapter_title(state.chapter),
            "chapter_turns": state.chapter_turns,
            "pacing": chapter_mod.pacing_status(state.chapter_turns),
            "frozen": chapter_mod.is_frozen(state),
            "time": state.time.model_dump(mode="json"),
            "settlement_id": settlement_result.facts.settlement_id,
            "context_version_id": settlement_result.version.version_id,
        }
