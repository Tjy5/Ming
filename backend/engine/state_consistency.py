from __future__ import annotations

"""确定性状态一致性校验层（教训4/7：文本与状态同源、防AI找补）。

职责（本任务子集，见 .trellis/tasks/08-07-state-consistency-verification/prd.md）：
- 硬状态源助手：以 GameState 为唯一事实源，产出"不可用人物"（REMOVED/IDLE）清单。
- 叙事文本校验器：检出两类不一致——不可用人物仍在发言/行事、虚构人物发言。
- 校验→重试→净化闭环：AI 叙事必须过校验后才可入库/返回前端。

不依赖任何 ai/ 层模块，避免与 engine/__init__ 的导入链成环
（调用方（如 ai/prompts.py）如需引用，使用函数内惰性导入，参见 trpg/writeback.py 约定）。
"""

import logging
import re

from models.enums import MinisterStatus
from models.game import GameState

logger = logging.getLogger(__name__)

# ── 硬状态源助手 ────────────────────────────────────────────

# REMOVED（处决/出局）与 IDLE（罢免）均为"不可用人物"：不得在 AI 叙事中发言或行事。
_UNAVAILABLE_REASONS = {
    MinisterStatus.REMOVED: "已处决/出局",
    MinisterStatus.IDLE: "已罢免",
}


def unavailable_actors(state: GameState) -> dict[str, str]:
    """不可用人物清单 {名字: 原因}（硬状态源，供校验与 prompt 守卫）。"""
    return {
        m.name: _UNAVAILABLE_REASONS[m.status]
        for m in state.ministers
        if m.status in _UNAVAILABLE_REASONS
    }


def active_actor_names(state: GameState) -> set[str]:
    return {m.name for m in state.ministers if m.status == MinisterStatus.ACTIVE}


def roster_names(state: GameState) -> set[str]:
    return {m.name for m in state.ministers}


# ── 校验规则常量 ─────────────────────────────────────────────

# 外部历史实体：作为背景人物允许被提及（不参与发言白名单，避免误报）。
EXTERNAL_ENTITIES = {
    "张士诚", "陈友谅", "徐寿辉", "察罕帖木儿", "扩廓帖木儿", "王保保",
    "元顺帝", "妥懽帖睦尔", "刘福通", "韩林儿", "小明王", "郭子兴",
    "方国珍", "明玉珍", "陈友定", "脱脱", "伯颜", "朱元璋", "刘基", "宋濂",
}

# 通用称谓/身份词：发言前缀匹配时跳过，避免把"臣：""士卒："当虚构人物。
_SPEAKER_TITLES = {
    "主公", "陛下", "皇上", "万岁", "臣", "朕", "本王", "孤", "寡人",
    "妾", "微臣", "老臣", "末将", "臣妾", "鄙人",
}

_COMMON_SPEAKERS = {
    "士卒", "百姓", "军民", "众臣", "群臣", "朝臣", "将士", "兵将",
    "斥候", "来使", "使者", "太监", "内侍", "宦官", "宫人", "侍女",
    "侍从", "下人", "奴婢", "军士", "兵丁", "乡绅", "士绅", "父老",
    "府吏", "县令", "巡抚", "参政", "都事", "典吏", "门官", "驿卒",
    "百官", "诸将", "诸臣",
}

# 排除后缀：以这些字结尾的 2-4 字 token 视为身份词/群体词，不判虚构人物发言。
_SKIP_SUFFIX = ("军", "士", "役", "卒", "臣", "官", "者", "人", "使", "卫", "仆", "婢", "卿", "民", "将")

# 活动性谓词：命中即视为"仍在发言/行事"。只收"活动性"动词——
# 被害性描述（处决/斩首/罢免/贬黜/致仕/病逝/阵亡/伏诛）不在此列，叙述处决事实本身合规。
_ACTIVITY_VERBS = (
    "说道", "说", "拱手道", "躬身道", "答道", "回禀", "禀告", "启奏",
    "跪奏", "上奏", "奏报", "进言", "谏言", "上书", "献计", "求见",
    "入朝", "上朝", "出朝", "赴朝", "主持", "署理", "赴任", "就职",
    "升任", "督师", "接管", "出使", "率兵", "领兵", "带兵", "提兵",
    "出兵", "率军", "领军", "统军", "挂帅", "就任", "担任", "执掌",
    "掌管", "督办", "受命", "奉诏", "拱手", "下令", "道",
)

# 朝堂活动动词（规则B 专用）：指向"我方朝堂"的活动，外部势力背景行事不算。
_COURT_ACTIVITY_VERBS = (
    "入朝", "上朝", "赴朝", "上奏", "跪奏", "奏报", "回禀", "禀告",
    "启奏", "进言", "谏言", "上书", "献计", "求见", "求觐", "受命",
    "奉诏", "署理", "督师",
)

# 发言前缀模式：句首 2-6 字中文 token 后跟全角/半角冒号。
_SPEECH_PREFIX_RE = re.compile(r"^([一-鿿·]{2,6})[:：]")

# 发言谓词尾缀（规则B 剥离用）：名字+说道/拱手道+冒号 时先剥出名字。最长优先。
# 群体齐声发言（"百官齐声道：""众人齐道：""将士齐呼："）整段剥离，避免把
# "齐声/齐道" 当人名一部分（与既有 "说道/道" 剥离的取舍一致）。
_SPEECH_TAIL_VERBS = (
    "齐声应道", "齐声道", "拱手道", "躬身道", "跪奏道", "齐声", "齐呼", "齐道",
    "答道", "说道", "奏道", "禀道", "道", "说",
)

# 过去时标记：名字+标记+活动谓词 是史实/生平叙述（"徐达生前率军""徐达当年入朝"），
# 不得误报为"仍在活动"（design 误报防护：过去式）。仅"活动性"语境使用——
# 处决事实（被害性动词）本就不在谓词表，无需额外处理。
_PAST_MARKERS = ("生前", "曾经", "当年", "昔日", "早年", "曾")

# 朝堂活动模式：2-4 字 token + 朝堂动词（规则B 行事检测）。
# 前置边界（句首或标点/空白）防止人名中段窗口误配（"徐达入朝" 不应切出 "达入朝"）；
# token 非贪婪（{2,4}?）使"徐达入朝上奏"正确切出 token=徐达 + 入朝，而非"徐达入朝"+"上奏"；
# group(2) 为命中的朝堂动词（供诊断信息）。
_COURT_ACTIVITY_RE = re.compile(
    r"(?:^|[，。！？!?；;、\s：:])([一-鿿·]{2,4}?)("
    + "|".join(_COURT_ACTIVITY_VERBS) + ")"
)

# 句子切分（与 api/state.py _split_stream_sentences 同款，engine 层不依赖 api 层）。
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")

# 净化后兜底叙事（空结果或过短时使用）。
FALLBACK_NARRATIVE = "政令已执行，朝野各有应对，国家自当随之变迁。"


# ── 校验器 ───────────────────────────────────────────────────

def _iter_sentences(text: str):
    for para in (text or "").split("\n"):
        for seg in _SENTENCE_SPLIT_RE.split(para):
            seg = seg.strip()
            if seg:
                yield seg


def _has_past_marker(gap: str | None) -> bool:
    """名字与活动谓词之间的窗口是否含过去时标记（是→史实/生平叙述，不判违规）。"""
    return bool(gap) and any(mk in gap for mk in _PAST_MARKERS)


def _strip_past_markers(token: str) -> str:
    """剥离 token 首尾的过去时标记（"徐达当年"→"徐达"，"当年徐达"→"徐达"）。"""
    changed = True
    while changed:
        changed = False
        for mk in _PAST_MARKERS:
            if token.startswith(mk):
                token = token[len(mk):]
                changed = True
            if token.endswith(mk):
                token = token[:-len(mk)]
                changed = True
    return token


def _check_unavailable_activity(sentence: str, state: GameState) -> list[dict]:
    """规则A：不可用人物仍在发言或行事。

    语义口径（与游戏状态机对齐）：
    - REMOVED（已处决/出局）：任何活动谓词都违规（全量 _ACTIVITY_VERBS）。
    - IDLE（已罢免/未出仕）：仅"我方朝堂活动"违规（朝堂动词子集 + 发言）；
      外部人物背景行事（如韩林儿率军）为合法史实，不误报。
    """
    issues: list[dict] = []
    reasons = _UNAVAILABLE_REASONS
    for m in state.ministers:
        if m.status not in reasons:
            continue
        name = m.name
        # 发言：名字（后随 0-2 字称谓如"拱手道"）后跟冒号，或名字后直接跟"说道/道"；
        # 名字与谓词间的窗口含过去时标记（"徐达生前说道"）→ 生平叙述，跳过
        speech = re.search(
            rf"{re.escape(name)}(?:([一-鿿]{{0,2}})(?:说道|拱手道|躬身道|答道|道))?[:：]",
            sentence,
        )
        if speech is not None and not _has_past_marker(speech.group(1)):
            issues.append({
                "type": "unavailable_actor_activity",
                "actor": name,
                "reason": f"{name}{reasons[m.status]}，不得描述其发言",
            })
            continue
        # 活动谓词：REMOVED 全量，IDLE 仅朝堂子集；窗口含过去时标记同样跳过
        verbs = _ACTIVITY_VERBS if m.status == MinisterStatus.REMOVED else _COURT_ACTIVITY_VERBS
        for verb in verbs:
            if verb in sentence:
                match = re.search(
                    rf"{re.escape(name)}(?=([一-鿿]{{0,2}}){re.escape(verb)})", sentence,
                )
                if match is not None and not _has_past_marker(match.group(1)):
                    issues.append({
                        "type": "unavailable_actor_activity",
                        "actor": name,
                        "reason": f"{name}{reasons[m.status]}，不得描述其行事（{verb}）",
                    })
                    break
    return issues


def _check_invented_speaker(sentence: str, state: GameState) -> list[dict]:
    """规则B：虚构人物发言（`名字：` 前缀）或行朝堂之事（名字+朝堂动词）。"""
    issues: list[dict] = []
    known_names = roster_names(state) | EXTERNAL_ENTITIES

    def _is_known(token: str) -> bool:
        if token in known_names:
            return True
        # 已知名尾缀（察罕帖木儿入朝 → token "帖木儿" 不误报）
        if any(name.endswith(token) for name in known_names):
            return True
        if token in _SPEAKER_TITLES or token in _COMMON_SPEAKERS:
            return True
        # 带身份前缀的群体词（传旨太监/军前斥候/东厂内侍…）：以常见身份词结尾则放行
        if any(token.endswith(cs) for cs in _COMMON_SPEAKERS):
            return True
        if token.endswith(_SKIP_SUFFIX):
            return True
        return False

    match = _SPEECH_PREFIX_RE.match(sentence)
    if match is not None:
        # 剥离发言谓词尾缀（徐达拱手道：→ 徐达），避免把动词短语当人名；
        # 再剥离过去时标记（"徐达生前说道"→"徐达"），生平叙述不判虚构发言
        token = match.group(1)
        for verb in _SPEECH_TAIL_VERBS:
            if token.endswith(verb):
                token = token[:-len(verb)]
                break
        token = _strip_past_markers(token)
        if len(token) < 2:
            token = ""
        if token and not _is_known(token):
            issues.append({
                "type": "invented_speaker",
                "actor": token,
                "reason": f"{token}不在当前人物名册，不得以发言者身份出现",
            })
    for match in _COURT_ACTIVITY_RE.finditer(sentence):
        token = match.group(1)
        # 剥离过去时标记（"徐达当年入朝"→"徐达"，"当年徐达入朝"→"徐达"）
        stripped = _strip_past_markers(token)
        if len(stripped) < 2:
            continue
        if not _is_known(stripped):
            verb = match.group(2)
            issues.append({
                "type": "invented_court_actor",
                "actor": stripped,
                "reason": f"{stripped}不在当前人物名册，不得行朝堂之事（{verb}）",
            })
    return issues


# 时代错乱词表（元末至正设定下不应出现的后代年号/事件）
_ANACHRONISMS = ("崇祯", "明朝", "永乐", "迁都北京", "建文帝", "朱棣", "北京城")


def _check_anachronism(sentence: str, state: GameState) -> list[dict]:
    """规则C（时代错乱）：元末设定下出现的后代年号/事件/人物。

    仅当 state 处于明朝建立前（year < 1368）才拦截，避免误伤后期剧本。
    """
    if getattr(state.time, "year", 9999) >= 1368:
        return []
    hits = [w for w in _ANACHRONISMS if w in sentence]
    if not hits:
        return []
    return [{
        "type": "anachronism",
        "actor": "",
        "reason": f"时代错乱：出现后代年号/事件 {hits}（当前为元末至正年间）",
    }]


def validate_narrative_against_dropped(text: str, dropped_out: list) -> list[dict]:
    """freeform 同源校验：叙事中出现"被丢弃 effects"的目标实体名 → 文本描述未生效内容。

    ``dropped_out`` 为 ``validate_ai_effects(..., dropped_out=...)`` 产出的
    (path, value, 原因) 列表；仅取 minister/region/faction 类路径的目标名。
    """
    names: set[str] = set()
    for path, _value, _reason in dropped_out:
        parts = str(path).split(".")
        if len(parts) >= 2 and parts[0] in ("minister", "region", "faction"):
            name = parts[1]
            if name:
                names.add(name)
    if not names:
        return []
    issues: list[dict] = []
    for sentence in _iter_sentences(text):
        for name in names:
            if name in sentence:
                issues.append({
                    "type": "dropped_effect_target",
                    "actor": name,
                    "reason": f"{name} 相关效果未生效（被规则层丢弃），叙事不得描述其变化",
                    "sentence": sentence,
                })
                break
    return issues


def validate_narrative_text(text: str, state: GameState) -> list[dict]:
    """校验叙事文本与硬状态的一致性。

    返回结构化 issue 列表：{"type", "actor", "reason", "sentence"}。
    无 issue 返回空列表。校验规则保持确定性（正则层），不做模型判断。
    """
    issues: list[dict] = []
    for sentence in _iter_sentences(text):
        for issue in _check_unavailable_activity(sentence, state):
            issue["sentence"] = sentence
            issues.append(issue)
        for issue in _check_invented_speaker(sentence, state):
            issue["sentence"] = sentence
            issues.append(issue)
        for issue in _check_anachronism(sentence, state):
            issue["sentence"] = sentence
            issues.append(issue)
    return issues


# ── 修复/净化 ────────────────────────────────────────────────

def build_retry_instruction(issues: list[dict]) -> str:
    lines = ["你的上一段叙事与当前游戏状态不一致，请重写全文并修正以下问题（不得再出现）："]
    for issue in issues:
        lines.append(f"- 「{issue['sentence']}」：{issue['reason']}")
    lines.append("其余要求不变；若无法自然表述，可省略违规内容。")
    return "\n".join(lines)


def sanitize_narrative(
    text: str, issues: list[dict], *, fallback: str = FALLBACK_NARRATIVE,
) -> str:
    """确定性净化：剔除含 issue 的句子；无剩余句子（或仅剩零星残句）时用模板兜底。"""
    flagged = {issue.get("sentence") for issue in issues if issue.get("sentence")}
    kept = [seg for seg in _iter_sentences(text) if seg not in flagged]
    cleaned = "".join(kept).strip()
    if len(cleaned) < 5:
        return fallback
    return cleaned


def build_prompt_guard(state: GameState) -> str:
    """prompt 硬约束守卫：把已处决/出局人物显式注入叙事 prompt（确定性，非提示性）。

    仅列 REMOVED：已出局人物禁一切活动，语义无歧义、数量少（避免 prompt 膨胀）。
    IDLE（未出仕/被罢免）不注入——名单庞大且多为合法史实背景人物（韩林儿/陈友谅等），
    其"我方朝堂活动"违规由确定性校验器（规则A IDLE 子集）事后拦截。
    """
    removed = {
        name: reason
        for name, reason in unavailable_actors(state).items()
        if reason == _UNAVAILABLE_REASONS[MinisterStatus.REMOVED]
    }
    if not removed:
        return ""
    items = "、".join(f"{name}（{reason}）" for name, reason in removed.items())
    return (
        "本回合以下人物不可作为活动人物出现：不得发言、不得上朝入朝、"
        f"不得率军行事、不得出任官职：{items}。"
        "（叙述处决/罢免事实本身不在此限。）"
    )


# ── 校验→重试→净化闭环 ──────────────────────────────────────

# 可诊断记录：供 benchmark（08-07-ai-benchmark-quality）与测试复用。每轮追加一条。
validation_log: list[dict] = []


def _log_validation(action: str, text: str, issues: list[dict] | None = None) -> None:
    validation_log.append({
        "action": action,
        "snippet": (text or "")[:80],
        "issue_count": len(issues) if issues else 0,
        "issues": issues or [],
    })
    if issues:
        logger.warning(
            "narrative consistency %s: %s", action,
            "; ".join(f"{i.get('actor')}: {i.get('reason')}" for i in issues),
        )


async def ensure_narrative_consistent(
    provider,
    state: GameState,
    *,
    generate,
    max_retries: int = 1,
) -> str:
    """叙事生成闭环：校验 → 重试（注入修复指令）→ 确定性净化。

    ``generate`` 必须是 ``async def generate(fix_instruction: str | None = None) -> str``。
    返回的文本保证通过校验（或为确定性兜底文本）。
    """
    text = await generate()
    issues = validate_narrative_text(text, state)
    if not issues:
        _log_validation("ok", text)
        return text
    _log_validation("issues", text, issues)

    attempt = 0
    while issues and attempt < max_retries:
        fix_instruction = build_retry_instruction(issues)
        text = await generate(fix_instruction=fix_instruction)
        issues = validate_narrative_text(text, state)
        _log_validation("retry", text, issues)
        attempt += 1

    if issues:
        sanitized = sanitize_narrative(text, issues)
        _log_validation("sanitized", sanitized)
        return sanitized
    return text


def sanitize_ai_text(text: str, state: GameState) -> str:
    """轻量路径（奏疏/总评等不重试）：校验 + 净化，保证入库文本合规。"""
    if not text:
        return text
    issues = validate_narrative_text(text, state)
    if not issues:
        return text
    _log_validation("sanitized_light", text, issues)
    return sanitize_narrative(text, issues)
