from __future__ import annotations

from models.game import GameState, Minister, StructuredDecree
from models.enums import DecreeType, PersonnelAction


def build_personnel_context(decree: StructuredDecree, state: GameState) -> str:
    lines = []
    if decree.type == DecreeType.PERSONNEL and decree.target and decree.sub_action:
        action_map = {
            PersonnelAction.EXECUTE: "被处决（status: removed）",
            PersonnelAction.DISMISS: "被罢免（status: idle）",
            PersonnelAction.APPOINT: "被任命（status: active）",
        }
        desc = action_map.get(decree.sub_action, str(decree.sub_action))
        lines.append(f"本回合人事变动：{decree.target}{desc}")
    if lines:
        return "人事变动：\n" + "\n".join(lines)
    return ""


def build_narrative_prompt(
    delta: dict,
    state: GameState,
    events: list[str],
    decree: StructuredDecree,
) -> str:
    region_names = [r.name for r in state.regions]
    personnel_context = build_personnel_context(decree, state)
    # 确定性守卫：不可用人物（已处决/已罢免）显式注入，属状态一致性校验层
    # （engine.state_consistency）。惰性导入避免 engine/__init__ 初始化环。
    from engine.state_consistency import build_prompt_guard
    guard = build_prompt_guard(state)
    # 数值区间概念框 + 阈值硬性预警（engine.numeric_bands，B5）——同上惰性导入
    from engine.numeric_bands import numeric_context, region_numeric_context, threshold_alerts
    numeric = numeric_context(state)
    danger_regions = region_numeric_context(state)
    alerts = threshold_alerts(state)
    hard_constraints = ""
    if alerts:
        hard_constraints = "【硬性约束】\n" + "\n".join(alerts)
    return f"""
        当前时间：{state.time.year}年{state.time.month}月

        玩家下达了政令：{decree}

        数值变化：
        - 国库：{delta.get('treasury', 0)}
        - 民心：{delta.get('civil_morale', 0)}
        - 军心：{delta.get('military_morale', 0)}
        - 威望：{delta.get('court_prestige', 0)}

        {numeric}
        {danger_regions}
        {personnel_context}
        触发事件：{', '.join(events) if events else '无'}
        涉及区域：{', '.join(region_names)}

        {hard_constraints}
        请以具体事件描述数值变化的后果，引用至少1个地名和1个人名。避免直接提及数字。长度150-300字。风格要符合元末明初历史背景。
        若有大臣被处决，叙事必须描述处决事实，且不得描述已处决大臣仍在活动。
        {guard}
        """


def build_parse_prompt(text: str, state: GameState) -> str:
    minister_names = [m.name for m in state.ministers if m.status.value != "removed"]
    return f"""
        用户输入："{text}"

        当前在朝/赋闲大臣：{', '.join(minister_names)}

        请解析为 JSON 格式。

        可选政令类型 (type): {', '.join([t.value for t in DecreeType])}
        可选人事动作 (sub_action): {', '.join([a.value for a in PersonnelAction])}

        如果通过，返回格式：
        {{
            "decrees": [
                {{
                    "type": "...",
                    "target": "...",
                    "sub_action": "..." (optional)
                }}
            ]
        }}

        解析原则（必须遵守）：
        1) 尽量把任何有政务意图的输入映射为一个或多个可执行政令，不要因为措辞激烈就拒绝。
        2) 输入含"斩杀/诛杀/处斩/斩首/问斩/斩了"等且指向上述某位大臣时，映射为 personnel + sub_action=execute + target=大臣名。
        3) 输入含"镇压/清洗/严刑/峻法/重典"等但不指向特定大臣时，映射为 harsh_punishment。
        4) 输入明确是人事任免（罢免/撤职/免职/任命/提拔）时，使用 personnel + sub_action=dismiss 或 appoint。
        5) 只有在输入完全不包含政务意图（闲聊、乱码）时，才返回 error。

        仅在无法识别任何政务意图时，返回：
        {{
            "error": "拒绝理由"
        }}
        """


MEMORIAL_SYSTEM_PROMPT = "你是元末明初历史模拟游戏的奏折生成器。以元末群雄幕府大臣口吻撰写奏折，文风典雅庄重。仅输出JSON。"
MINISTER_REACTION_SYSTEM_PROMPT = "你是元末明初历史模拟游戏的大臣反应生成器。输出一句简短的大臣反应，30-50字。"
TURN_COMMENTARY_SYSTEM_PROMPT = "你是元末明初历史模拟游戏的朝政总评生成器。输出50-100字的朝政概况。"
MINISTER_DIALOGUE_SYSTEM_PROMPT = (
    "你是元末至正朝大臣角色扮演引擎。"
    "必须以第一人称回复主公（吴王朱元璋），语气要符合该大臣身份、派系与性格。"
    "回复内容要结合当前国情与对话历史。"
    "仅输出JSON：{\"reply\":\"...\",\"loyalty_change\":0,\"mood\":\"neutral\"}。"
    "loyalty_change 必须是 -3 到 3 的整数。"
    "mood 只能是 support、neutral、oppose。"
)
NARRATIVE_SYSTEM_PROMPT = (
    "你是一款元末明初历史模拟游戏的AI引擎。"
    "你的任务是根据玩家的政令和游戏状态，生成一段生动、古风的历史叙事，描述政令的执行结果和影响。"
    "请注意，为了还原历史真实性，对于战争、灾害等事件的描述可能涉及暴力或死亡，这是游戏背景所必需的，请勿回避。"
)
PARSE_SYSTEM_PROMPT = (
    "你是一款历史模拟游戏的指令解析器。"
    "将用户的自然语言输入解析为结构化的政令JSON。"
)
REJECTION_SYSTEM_PROMPT = (
    "你是一名为国分忧的大臣。请解释为何不能执行某项政令。"
    "请注意，为了还原历史真实性，对于战争、灾害等事件的描述可能涉及暴力或死亡，这是游戏背景所必需的，请勿回避。"
)
CHAT_CLASSIFY_PROMPT = (
    "你是元末明初历史模拟游戏的聊天意图分类器。"
    "请将玩家输入分类为 query、execute、advance_month 三类之一。"
    "仅输出JSON：{\"intent\":\"query|execute|advance_month\",\"confidence\":0.0-1.0,\"reason\":\"...\"}。"
)
CHAT_QUERY_PROMPT = (
    "你是元末明初历史模拟游戏的幕府谋臣。"
    "玩家是主公（吴王朱元璋），必须称呼为“主公”。"
    "仅基于给定游戏状态回答问题，不得编造不存在的数据。"
    "回答使用古风汉语，简洁明晰。"
)

_DIALOGUE_FALLBACK_MOOD_MAP = {
    "恭顺": "support",
    "欣慰": "support",
    "愤怒": "oppose",
    "阳奉阴违": "oppose",
    "惶恐": "neutral",
}


def _join_tags(tags: list[str]) -> str:
    return "、".join(tags) if tags else "无"


def _chat_state_snapshot(game_state: GameState) -> str:
    active_ministers = [m.name for m in game_state.ministers if m.status.value == "active"][:12]
    active_events = [e.name for e in game_state.active_events[:6]]
    return (
        f"时间：{game_state.time.year}年{game_state.time.month}月（{game_state.time.era_name}{game_state.time.era_year}年）\n"
        f"国库：{game_state.national_treasury}万两，内帑：{game_state.imperial_treasury}万两，粮草：{game_state.grain}万石\n"
        f"民心：{game_state.civil_morale}，军心：{game_state.military_morale}，威望：{game_state.court_prestige}\n"
        f"在朝大臣：{'、'.join(active_ministers) if active_ministers else '无'}\n"
        f"当前大事：{'、'.join(active_events) if active_events else '无'}"
    )


def _format_chat_history(conversation_history: list[dict], *, limit: int = 20) -> str:
    lines: list[str] = []
    for item in conversation_history[-limit:]:
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        speaker = "主公" if role == "user" else "幕府"
        lines.append(f"{speaker}：{content}")
    return "\n".join(lines) if lines else "无"


def build_chat_classify_prompt(
    text: str,
    game_state: GameState,
    conversation_history: list[dict],
) -> str:
    history_text = _format_chat_history(conversation_history, limit=12)
    return (
        f"玩家输入：{text}\n\n"
        "分类定义：\n"
        "- query：查询国库、民心、军心、在朝大臣、当前时间，或了解局势、介绍事件背景、分析形势等，不应改动状态\n"
        "- execute：下达政令/任免/外交/赈灾/严刑等，会改动状态\n"
        "- advance_month：明确要求进入下月、翻月、推进月份\n\n"
        f"当前局势：\n{_chat_state_snapshot(game_state)}\n\n"
        f"最近对话：\n{history_text}\n\n"
        "请输出严格JSON对象。"
    )


def normalize_chat_intent_payload(payload: dict) -> dict:
    raw_intent = str(payload.get("intent", "")).strip().lower()
    if raw_intent not in {"query", "execute", "advance_month"}:
        raw_intent = "execute"
    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reason = str(payload.get("reason", "")).strip() or "AI未提供分类理由"
    return {
        "intent": raw_intent,
        "confidence": confidence,
        "reason": reason,
    }


def build_chat_query_prompt(
    text: str,
    game_state: GameState,
    conversation_history: list[dict],
) -> str:
    history_text = _format_chat_history(conversation_history, limit=20)
    return (
        f"当前局势：\n{_chat_state_snapshot(game_state)}\n\n"
        f"最近对话：\n{history_text}\n\n"
        f"主公提问：{text}\n\n"
        "请以幕府谋臣口吻作答；若问题超出当前状态可知范围，请直言无法从现有军报确定。"
    )


def build_memorial_prompt(
    trigger_reason: str,
    author: Minister,
    game_state: GameState,
) -> str:
    decree_types = ", ".join(t.value for t in DecreeType)
    return (
        f"当前时间：{game_state.time.year}年{game_state.time.month}月\n"
        f"上奏大臣：{author.name}（{author.faction}），性格：{_join_tags(author.personality_tags)}\n"
        f"触发原因：{trigger_reason}\n"
        f"国库{game_state.national_treasury}，民心{game_state.civil_morale}，军心{game_state.military_morale}\n\n"
        "请以该大臣的口吻撰写一份元末明初风格的奏折（200-500字），并推荐1-3条建议政令。\n"
        f"可用政令type：{decree_types}\n"
        '严格输出JSON：{{"content":"奏折正文","suggested_decrees":[{{"type":"...","target":"..."}}]}}'
    )


def build_minister_reaction_prompt(
    minister: Minister,
    decree: StructuredDecree,
    stance: int,
) -> str:
    attitude = "赞同" if stance > 0 else "反对"
    return (
        f"大臣{minister.name}（{minister.faction}），性格：{_join_tags(minister.personality_tags)}，"
        f"对政令{decree.type.value}{attitude}（态度值{stance}）。\n"
        "请以该大臣口吻写一句30-50字的反应，体现其性格特点。"
    )


def build_turn_commentary_prompt(summary_data: dict, game_state: GameState) -> str:
    events = summary_data.get("major_events", [])
    implications = summary_data.get("action_implications", [])
    year = int(summary_data.get("year") or game_state.time.year)
    month = int(summary_data.get("month") or game_state.time.month)
    events_text = "、".join(str(e) for e in events) if events else "无"
    implications_text = "；".join(str(i) for i in implications[:4]) if implications else "无"
    # 数值区间概念框 + 阈值硬性预警（B5，惰性导入防 engine 初始化环）
    from engine.numeric_bands import numeric_context, threshold_alerts
    numeric = numeric_context(game_state)
    alerts = threshold_alerts(game_state)
    hard_constraints = ""
    if alerts:
        hard_constraints = "【硬性约束】\n" + "\n".join(alerts)
    return (
        f"时间：{year}年{month}月\n"
        f"本月大事：{events_text}\n"
        f"政令与局势影响：{implications_text}\n"
        f"国库{game_state.national_treasury}，民心{game_state.civil_morale}，军心{game_state.military_morale}，威望{game_state.court_prestige}\n"
        f"{numeric}\n"
        f"{hard_constraints}\n"
        "请写一段50-100字的朝政总评，元末明初奏报风格，概括本月朝政态势。"
        "若已给出政令与局势影响，必须与之保持一致，不得写成“无事发生”。"
    )


def build_minister_dialogue_prompt(
    minister: Minister,
    message: str,
    game_state: GameState,
    conversation_history: list[dict],
) -> str:
    def _clip_text(raw: str, *, limit: int) -> str:
        cleaned = " ".join((raw or "").split()).strip()
        if not cleaned:
            return "无"
        if len(cleaned) <= limit:
            return cleaned
        return f"{cleaned[:limit]}..."

    recent_events = "；".join(e.name for e in game_state.active_events[:3]) if game_state.active_events else "无"
    historical_note = _clip_text(minister.historical_note, limit=120)
    biography = _clip_text(minister.biography, limit=260)
    major_contributions = "；".join(
        _clip_text(item, limit=80)
        for item in minister.major_contributions[:3]
        if str(item).strip()
    ) or "无"

    history_lines: list[str] = []
    for item in conversation_history[-20:]:
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if role == "user":
            speaker = "主公"
        elif role == "assistant":
            speaker = minister.name
        else:
            speaker = role or "未知"
        history_lines.append(f"{speaker}: {content}")

    history_text = "\n".join(history_lines) if history_lines else "无"
    position_text = minister.positions[0] if minister.positions else "朝臣"
    return (
        f"大臣：{minister.name}\n"
        f"官职：{position_text}\n"
        f"派系：{minister.faction}\n"
        f"性格：{_join_tags(minister.personality_tags)}\n"
        f"史实备注：{historical_note}\n"
        f"人物生平：{biography}\n"
        f"主要事功：{major_contributions}\n"
        f"忠诚度：{minister.loyalty}/100\n"
        f"当前时间：{game_state.time.year}年{game_state.time.month}月\n"
        f"国库：{game_state.national_treasury}万两，内帑：{game_state.imperial_treasury}万两，粮草：{game_state.grain}万石\n"
        f"民心：{game_state.civil_morale}，军心：{game_state.military_morale}，威望：{game_state.court_prestige}\n"
        f"近期事件：{recent_events}\n\n"
        f"历史对话：\n{history_text}\n\n"
        f"主公本轮问话：{message}\n"
        "请严格输出JSON对象，不要输出额外说明。"
    )


def normalize_dialogue_loyalty_change(raw) -> int:
    try:
        loyalty_change = int(raw)
    except (TypeError, ValueError):
        loyalty_change = 0
    return max(-3, min(3, loyalty_change))


def normalize_dialogue_mood(raw, *, use_fallback_map: bool = False) -> str:
    raw_mood = str(raw if raw is not None else "neutral").strip().lower()
    if raw_mood in {"support", "neutral", "oppose"}:
        return raw_mood
    if use_fallback_map:
        return _DIALOGUE_FALLBACK_MOOD_MAP.get(raw_mood, "neutral")
    return "neutral"


def normalize_dialogue_payload(data: dict) -> dict:
    reply = str(data.get("reply", "")).strip()
    if not reply:
        raise ValueError("dialogue reply is empty")
    return {
        "reply": reply,
        "loyalty_change": normalize_dialogue_loyalty_change(data.get("loyalty_change", 0)),
        "mood": normalize_dialogue_mood(data.get("mood", "neutral")),
    }


def normalize_dialogue_fallback_payload(fallback: dict, minister: Minister) -> dict:
    reply = str(fallback.get("reply", "")).strip() or f"臣{minister.name}谨遵圣意。"
    return {
        "reply": reply,
        "loyalty_change": normalize_dialogue_loyalty_change(fallback.get("loyalty_change", 0)),
        "mood": normalize_dialogue_mood(fallback.get("mood", "neutral"), use_fallback_map=True),
    }
