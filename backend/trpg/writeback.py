"""跑团 ↔ 治理回写桥（阶段D，design 第 3 节）。

- `apply_state_changes`：/act GM state_changes 应用层——按 engine/tables.py
  WRITABLE_FIELDS 白名单校验 + 类型检查（int/float 按增量 += 应用、str 直接
  设置并校验取值），合法应用、非法丢弃并记日志（不抛错、不阻断）。
- 治理 → 跑团回写钩子（engine 内部结算点调用，直接写玩家角色卡，**不经 AI
  白名单**——SYSTEM_FIELDS 禁的是治理 AI 改 character_sheets，与此路径无关）：
  战败 → 军事 -2 + 状态"挫败"；民心崩溃 → 政治 -2；大臣叛离 → 特质"多疑"。
  角色卡缺失（新档未生成）时安全跳过。
"""
from __future__ import annotations

import logging

from models.enums import MinisterStatus, RegionControl, RegionThreat
from models.game import GameState
from models.trpg import PLAYER_NAME
from trpg import character as character_mod

logger = logging.getLogger(__name__)

# 民心崩溃阈值：结算后 civil_morale 不高于该值视为崩溃（政治 -2）
CIVIL_COLLAPSE_THRESHOLD = 10

# 白名单 str 字段 → 目标模型枚举（直接 setattr 不触发 pydantic 强转，
# 需显式转枚举保证后续比较一致）；valid 集已校验，取值必合法。
_STR_FIELD_ENUMS: dict[str, object] = {
    "control": RegionControl,
    "threat": RegionThreat,
    "status": MinisterStatus,
}


# ── /act GM state_changes 应用层 ─────────────────────────

def apply_state_changes(
    state: GameState,
    changes: dict,
    *,
    executor_name: str | None = None,
) -> dict:
    """按 WRITABLE_FIELDS 白名单应用 GM state_changes。

    返回 {"applied": [...], "ignored": [...]}（键清单，供 /act 响应透出）。
    白名单外键 / 目标实体不存在 / 类型错误 / str 取值不合法 → 丢弃并记日志。
    """
    applied: list[str] = []
    ignored: list[str] = []
    if not isinstance(changes, dict):
        return {"applied": applied, "ignored": ignored}
    for key, raw_value in changes.items():
        if not isinstance(key, str) or not key.strip():
            ignored.append(str(key))
            continue
        if _apply_one(state, key.strip(), raw_value, executor_name=executor_name):
            applied.append(key.strip())
        else:
            ignored.append(key.strip())
    return {"applied": applied, "ignored": ignored}


def _pattern_matches(pattern: str, key: str) -> bool:
    if pattern == key:
        return True
    pat_parts = pattern.split(".")
    key_parts = key.split(".")
    if len(pat_parts) != len(key_parts):
        return False
    return all(p == "*" or p == k for p, k in zip(pat_parts, key_parts))


def _match_whitelist(key: str) -> dict | None:
    # 惰性导入避免循环：engine/__init__ 会立即加载 engine.core（其模块级
    # 导入 trpg.writeback），若此处模块级 import engine.tables，则以 trpg
    # 为首个导入的进程会 ImportError。调用时 engine 已加载完毕，无此问题。
    from engine.tables import WRITABLE_FIELDS

    for pattern, spec in WRITABLE_FIELDS.items():
        if _pattern_matches(pattern, key):
            return spec
    return None


def _resolve_target(state: GameState, key: str):
    parts = key.split(".")
    if parts[0] == "global":
        return state
    if parts[0] == "minister":
        minister = next((m for m in state.ministers if m.name == parts[1]), None)
        if minister is None:
            return None
        # 4 段键（minister.*.abilities.<attr>）→ 落到 abilities 子对象
        if len(parts) == 4 and parts[2] == "abilities":
            return minister.abilities
        return minister
    if parts[0] == "faction":
        return next((f for f in state.factions if f.name == parts[1]), None)
    if parts[0] == "region":
        return next((r for r in state.regions if r.name == parts[1]), None)
    return None


def _apply_one(
    state: GameState,
    key: str,
    raw_value,
    *,
    executor_name: str | None = None,
) -> bool:
    spec = _match_whitelist(key)
    if spec is None:
        logger.info("state_changes 忽略（不在白名单）: %s", key)
        return False
    target = _resolve_target(state, key)
    if target is None:
        logger.info("state_changes 忽略（目标实体不存在）: %s", key)
        return False
    field = key.rsplit(".", 1)[-1]
    parts = key.split(".")
    ftype = spec["type"]
    try:
        if ftype == "str":
            value = str(raw_value).strip()
            valid = spec.get("valid") or set()
            if value not in valid:
                logger.info("state_changes 忽略（%s 取值 %r 不合法）", key, value)
                return False
            enum_cls = _STR_FIELD_ENUMS.get(field)
            setattr(target, field, enum_cls(value) if enum_cls is not None else value)
            return True
        if ftype == "int":
            delta = int(raw_value)
            # 08-07-decree-execution-loss：全局数值增量经执行损耗，防止跑团 GM 绕过
            if parts[0] == "global":
                from engine.execution_loss import apply_execution_loss
                net = apply_execution_loss(
                    state,
                    {field: delta},
                    executor_name=executor_name,
                    action_kind="governance",
                )
                delta = net.get(field, delta)
            setattr(target, field, getattr(target, field) + delta)
            return True
        if ftype == "float":
            delta = round(float(raw_value), 2)
            # 同上：全局 float 增量（如税收比例）经损耗
            if parts[0] == "global":
                from engine.execution_loss import apply_execution_loss
                net = apply_execution_loss(
                    state,
                    {field: delta},
                    executor_name=executor_name,
                    action_kind="governance",
                )
                delta = net.get(field, delta)
            setattr(target, field, round(getattr(target, field) + delta, 2))
            return True
    except (TypeError, ValueError):
        logger.info("state_changes 忽略（类型错误）: %s = %r", key, raw_value)
        return False
    return False


# ── 治理 → 跑团回写钩子（engine 内部结算点调用）───────────

def writeback_defeat(state: GameState) -> bool:
    """战败回写：玩家军事 -2 + 状态"挫败"。

    以"挫败"状态为闸口（同一局内仅回写一次，防连续战败反复扣属性）。
    """
    player = character_mod.get_sheet(state, PLAYER_NAME)
    if player is None or "挫败" in player.status:
        return False
    player.attrs["军事"] = max(0, player.attrs.get("军事", 0) - 2)
    player.status.append("挫败")
    return True


def writeback_civil_collapse(state: GameState) -> bool:
    """民心崩溃回写：玩家政治 -2（结算后民心 ≤ 阈值时由调用方触发）。"""
    player = character_mod.get_sheet(state, PLAYER_NAME)
    if player is None:
        return False
    player.attrs["政治"] = max(0, player.attrs.get("政治", 0) - 2)
    return True


def writeback_minister_betrayal(state: GameState, minister_name: str) -> bool:
    """大臣叛离回写：确定性记录玩家获得的"多疑"后果。

    叛离登记（loyalty_zero_triggered）由 apply_betrayal_check 负责，此处只处理特质。
    """
    player = character_mod.get_sheet(state, PLAYER_NAME)
    if player is None:
        return False
    if "多疑" not in player.traits:
        player.traits.append("多疑")
    return True


def apply_betrayal_check(state: GameState) -> list[str]:
    """结算点钩子：忠诚归零的在朝大臣视为叛离（一次性，复用 loyalty_zero_triggered）。

    返回触发叛离回写（且获得特质）的大臣名单；忠诚为零但在朝的大臣只登记一次。
    """
    betrayed: list[str] = []
    for m in state.ministers:
        if m.status != MinisterStatus.ACTIVE:
            continue
        if m.loyalty > 0 or m.name in state.loyalty_zero_triggered:
            continue
        state.loyalty_zero_triggered.add(m.name)
        if writeback_minister_betrayal(state, m.name):
            betrayed.append(m.name)
    return betrayed
