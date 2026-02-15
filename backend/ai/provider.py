from __future__ import annotations

import abc
import asyncio
import logging
import os
import re
from dotenv import load_dotenv

from models.game import GameState, StructuredDecree, Minister, DebateResult, DebateMinister
from models.enums import DecreeType, PersonnelAction

PARSE_ERROR_TYPE_PARSE = "parse_error"
PARSE_ERROR_TYPE_UNAVAILABLE = "service_unavailable"


def parse_error(message: str, error_type: str = PARSE_ERROR_TYPE_PARSE) -> dict:
    return {"error": message, "error_type": error_type}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


RULE_PARSE_FALLBACK_ENABLED = _env_bool("AI_RULE_PARSE_FALLBACK", False)


def _is_non_retryable_portrait_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    markers = (
        "model_not_found",
        "429",
        "rate limit",
        "too many requests",
        "quota",
        "无可用渠道",
        "请求数限制",
        "invalid_api_key",
        "authentication",
        "permission",
    )
    return any(m in msg for m in markers)


class AIProvider(abc.ABC):
    @abc.abstractmethod
    async def generate_narrative(
        self, delta_attribution: dict, game_state: GameState,
        chain_events: list[str], decree: StructuredDecree,
    ) -> str: ...

    @abc.abstractmethod
    async def parse_free_input(
        self, text: str, game_state: GameState,
    ) -> list[StructuredDecree] | dict: ...

    @abc.abstractmethod
    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str: ...

    @abc.abstractmethod
    async def generate_debate_narrative(
        self, topic: str, minister_a: Minister, minister_b: Minister, game_state: GameState,
    ) -> DebateResult | None: ...

    @abc.abstractmethod
    async def generate_portrait(self, minister_name: str, description: str) -> str | None: ...


# ── Mock Provider ────────────────────────────────────────

NARRATIVE_TEMPLATES: dict[DecreeType, str] = {
    DecreeType.TAX_INCREASE:     "朕下旨加征赋税，国库增银{treasury}万两。然百姓怨声载道，民心{civil_morale}。{chain}",
    DecreeType.TAX_DECREASE:     "朕体恤百姓，下旨减免赋税。国库虽减{treasury}，民心却得{civil_morale}之振。{chain}",
    DecreeType.RECRUIT_TROOPS:   "朕令各地募兵备战，军备增{military_supply}，然征兵之费耗银{treasury}，百姓亦有离散。{chain}",
    DecreeType.DISBAND_TROOPS:   "朕令裁撤冗兵，省银{treasury}万两，然军备减{military_supply}，将士离心。{chain}",
    DecreeType.PERSONNEL:        "朕调整朝廷人事，威望{court_prestige}。朝堂格局为之一变。{chain}",
    DecreeType.DIPLOMACY:        "朕遣使出使{target}，费银{treasury}万两。军心{military_morale}，朝廷威望{court_prestige}。{chain}",
    DecreeType.DISASTER_RELIEF:  "朕拨银赈济{target}，费银{treasury}万两。灾民感恩戴德，民心{civil_morale}。{chain}",
    DecreeType.HARSH_PUNISHMENT: "朕下旨严刑峻法，以正纲纪。然百姓畏惧，民心{civil_morale}。{chain}",
}

REJECTION_TEMPLATES: dict[DecreeType, str] = {
    DecreeType.TAX_INCREASE:     "陛下，民心已然不稳，再加赋税恐激民变。臣请陛下三思。",
    DecreeType.TAX_DECREASE:     "陛下，国库空虚，实难再减赋税。臣请陛下先充实国库。",
    DecreeType.RECRUIT_TROOPS:   "陛下，钱粮或人口不足，难以征兵。臣请陛下筹措资源后再议。",
    DecreeType.DISBAND_TROOPS:   "陛下，军备不足，裁兵恐致边防空虚。臣请陛下慎重。",
    DecreeType.PERSONNEL:        "陛下，朝廷威望不足以服众，此时人事变动恐生乱象。",
    DecreeType.DIPLOMACY:        "陛下，国库不足以支撑外交使费。臣请陛下先充实国库。",
    DecreeType.DISASTER_RELIEF:  "陛下，国库仅余有限银两，实难拨付赈灾银两。臣请陛下先充实国库，再议赈济之事。",
    DecreeType.HARSH_PUNISHMENT: "陛下，朝廷威望不足，严刑峻法恐适得其反。",
}

NEGATION_KEYWORDS = re.compile(r"不要|别|勿|禁止")

KEYWORD_MAP: list[tuple[re.Pattern, DecreeType, dict | None]] = [
    (re.compile(r"加税|加征|增税|征税|加赋"), DecreeType.TAX_INCREASE, None),
    (re.compile(r"减税|免税|降税|减赋"), DecreeType.TAX_DECREASE, None),
    (re.compile(r"招兵|募兵|增兵|征兵"), DecreeType.RECRUIT_TROOPS, None),
    (re.compile(r"裁兵|裁军|遣散|削兵"), DecreeType.DISBAND_TROOPS, None),
    (re.compile(r"任命|提拔|擢升"), DecreeType.PERSONNEL, {"sub_action": PersonnelAction.APPOINT}),
    (re.compile(r"罢免|撤职|贬谪|免职|问罪"), DecreeType.PERSONNEL, {"sub_action": PersonnelAction.DISMISS}),
    (re.compile(r"外交|遣使|出使|议和"), DecreeType.DIPLOMACY, None),
    (re.compile(r"赈灾|赈济|救灾|拨银"), DecreeType.DISASTER_RELIEF, None),
    (re.compile(r"严刑|峻法|严法|重典|酷刑"), DecreeType.HARSH_PUNISHMENT, None),
    (re.compile(r"斩首|斩杀|问斩|处斩|诛杀|诛灭"), DecreeType.HARSH_PUNISHMENT, None),
]

REGION_KEYWORDS = re.compile(r"京畿|辽东|陕西|江南|中原|山东|云贵|川蜀")
DIPLOMACY_KEYWORDS = re.compile(r"后金|蒙古|朝鲜")
PERSON_PATTERN = re.compile(r"(?:把|将|令|命)?([^\s,，。、]{2,4})(?:调|贬|擢|免|罢|任|撤)")


def _format_delta(val: int) -> str:
    return f"+{val}" if val > 0 else str(val)


class MockProvider(AIProvider):
    async def generate_narrative(
        self, delta_attribution: dict, game_state: GameState,
        chain_events: list[str], decree: StructuredDecree,
    ) -> str:
        tpl = NARRATIVE_TEMPLATES[decree.type]
        vals = {}
        for key in ("treasury", "population", "military_supply", "civil_morale", "military_morale", "court_prestige"):
            total = 0
            if key in delta_attribution:
                total = sum(delta_attribution[key].values())
            vals[key] = _format_delta(total)
        vals["target"] = decree.target or ""
        vals["chain"] = "".join(f"【{e}】事件爆发！" for e in chain_events) if chain_events else ""
        return tpl.format(**vals)

    async def parse_free_input(
        self, text: str, game_state: GameState,
    ) -> list[StructuredDecree] | dict:
        if NEGATION_KEYWORDS.search(text):
            return parse_error("检测到否定指令，请直接描述您想执行的政令")
        results: list[StructuredDecree] = []
        for pattern, dtype, extra in KEYWORD_MAP:
            if pattern.search(text):
                kwargs: dict = {"type": dtype}
                if extra and "sub_action" in extra:
                    kwargs["sub_action"] = extra["sub_action"]
                    m = PERSON_PATTERN.search(text)
                    if m:
                        kwargs["target"] = m.group(1)
                if dtype == DecreeType.DISASTER_RELIEF:
                    m = REGION_KEYWORDS.search(text)
                    if m:
                        kwargs["target"] = m.group(0)
                if dtype == DecreeType.DIPLOMACY:
                    m = DIPLOMACY_KEYWORDS.search(text)
                    if m:
                        kwargs["target"] = m.group(0)
                results.append(StructuredDecree(**kwargs))
        if not results:
            return parse_error("无法识别具体政令，请使用按钮操作或描述具体政令内容")
        return results

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        return REJECTION_TEMPLATES.get(decree.type, f"陛下，此令无法执行：{reason}")

    async def generate_debate_narrative(
        self, topic: str, minister_a: Minister, minister_b: Minister, game_state: GameState,
    ) -> DebateResult | None:
        return None

    async def generate_portrait(self, minister_name: str, description: str) -> str | None:
        return None


async def _local_rule_parse(
    text: str, game_state: GameState,
) -> list[StructuredDecree] | None:
    """Fallback parser using local keyword rules when AI parser rejects input."""
    fallback = await MockProvider().parse_free_input(text, game_state)
    if isinstance(fallback, dict):
        return None
    validated = _validate_decrees(fallback)
    if isinstance(validated, dict):
        return None
    return validated


# ── Factory ──────────────────────────────────────────────

# from .openai_provider import OpenAIProvider  <-- REMOVED

_PROVIDERS: dict[str, type[AIProvider]] = {
    "mock": MockProvider,
    # "openai": OpenAIProvider, <-- REMOVED
}

_VALID_DECREE_TYPES = {t.value for t in DecreeType}


def get_provider(name: str | None = None) -> AIProvider:
    if name is None:
        load_dotenv()
        name = os.getenv("AI_PROVIDER", "mock")
    
    if name == "openai":
         from .openai_provider import OpenAIProvider
         return ResilientProvider(OpenAIProvider())

    if name == "google":
         from .google_provider import GoogleProvider
         return ResilientProvider(GoogleProvider())

    if name == "h":
         from .h_provider import HProvider
         return ResilientProvider(HProvider())

    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown AI provider: {name}")
    return ResilientProvider(cls())


# ── Timeout / Retry / Validation Wrapper ─────────────────

class ResilientProvider(AIProvider):
    """Wraps any AIProvider with timeout, retry, and output validation."""

    def __init__(self, inner: AIProvider, timeout: float = 30.0, retries: int = 3):
        self._inner = inner
        self._timeout = timeout
        self._retries = retries

    async def generate_narrative(
        self, delta_attribution: dict, game_state: GameState,
        chain_events: list[str], decree: StructuredDecree,
    ) -> str:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.generate_narrative(delta_attribution, game_state, chain_events, decree),
                    timeout=self._timeout,
                )
            except Exception as e:
                logging.error(f"generate_narrative attempt {attempt+1}/{self._retries} failed: {e}")
                if attempt == self._retries - 1:
                    return "（AI服务响应异常，但政令已执行）"
        return "（AI服务响应异常，但政令已执行）"

    async def parse_free_input(
        self, text: str, game_state: GameState,
    ) -> list[StructuredDecree] | dict:
        for attempt in range(self._retries):
            try:
                result = await asyncio.wait_for(
                    self._inner.parse_free_input(text, game_state),
                    timeout=self._timeout,
                )
                if isinstance(result, dict):
                    if RULE_PARSE_FALLBACK_ENABLED:
                        fallback = await _local_rule_parse(text, game_state)
                        if fallback is not None:
                            return fallback
                    return result
                return _validate_decrees(result)
            except Exception as e:
                logging.error(f"parse_free_input attempt {attempt+1}/{self._retries} failed: {e}")
                if attempt == self._retries - 1:
                    if RULE_PARSE_FALLBACK_ENABLED:
                        fallback = await _local_rule_parse(text, game_state)
                        if fallback is not None:
                            return fallback
                    return parse_error(
                        "AI解析服务暂时不可用，请使用按钮操作",
                        PARSE_ERROR_TYPE_UNAVAILABLE,
                    )
        if RULE_PARSE_FALLBACK_ENABLED:
            fallback = await _local_rule_parse(text, game_state)
            if fallback is not None:
                return fallback
        return parse_error(
            "AI解析服务暂时不可用，请使用按钮操作",
            PARSE_ERROR_TYPE_UNAVAILABLE,
        )

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.rejection_narrative(decree, reason),
                    timeout=self._timeout,
                )
            except Exception as e:
                logging.error(f"rejection_narrative attempt {attempt+1}/{self._retries} failed: {e}")
                if attempt == self._retries - 1:
                    return f"此令无法执行：{reason}"
        return f"此令无法执行：{reason}"

    async def generate_debate_narrative(
        self, topic: str, minister_a: Minister, minister_b: Minister, game_state: GameState,
    ) -> DebateResult | None:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.generate_debate_narrative(topic, minister_a, minister_b, game_state),
                    timeout=self._timeout,
                )
            except Exception as e:
                logging.error(f"generate_debate_narrative attempt {attempt+1}/{self._retries} failed: {e}")
                if attempt == self._retries - 1:
                    return None
        return None

    async def generate_portrait(self, minister_name: str, description: str) -> str | None:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.generate_portrait(minister_name, description),
                    timeout=self._timeout,
                )
            except Exception as e:
                logging.error(f"generate_portrait attempt {attempt+1}/{self._retries} failed: {e}")
                if _is_non_retryable_portrait_error(e):
                    return None
                if attempt == self._retries - 1:
                    return None
        return None


# ── Shared Helpers ────────────────────────────────────────

def build_debate_prompt(
    topic: str, minister_a: Minister, minister_b: Minister, game_state: GameState,
) -> str:
    def _tags(m: Minister) -> str:
        return "、".join(m.personality_tags) if m.personality_tags else "无"

    return (
        f"辩论议题：{topic}\n\n"
        f"大臣甲：{minister_a.name}（{minister_a.faction}），"
        f"性格：{_tags(minister_a)}，"
        f"文治{minister_a.abilities.civil}/武略{minister_a.abilities.military}/外交{minister_a.abilities.diplomacy}\n\n"
        f"大臣乙：{minister_b.name}（{minister_b.faction}），"
        f"性格：{_tags(minister_b)}，"
        f"文治{minister_b.abilities.civil}/武略{minister_b.abilities.military}/外交{minister_b.abilities.diplomacy}\n\n"
        f"当前国情：{game_state.time.year}年{game_state.time.month}月，"
        f"国库{game_state.treasury}，民心{game_state.civil_morale}，"
        f"军心{game_state.military_morale}，威望{game_state.court_prestige}\n\n"
        "请严格输出JSON，不要输出额外说明文字。"
    )


DEBATE_SYSTEM_PROMPT = (
    "你是崇祯模拟器的朝堂辩论生成器。仅输出一个JSON对象，不要输出Markdown代码块或额外文字。"
    "字段：debate_text（200-300字），minister_a_position（≤50字），minister_b_position（≤50字），"
    "option_a（{type,target,sub_action}），option_b（同），keywords（字符串数组，≤5个，去重）。"
    "type只能是：tax_increase,tax_decrease,recruit_troops,disband_troops,personnel,diplomacy,disaster_relief,harsh_punishment。"
    "sub_action仅在type=personnel时可用，且只能是appoint或dismiss；其它类型必须为null或省略。"
)


def parse_debate_response(
    data: dict, minister_a: Minister, minister_b: Minister,
) -> DebateResult | None:
    option_a = _parse_decree_option(data.get("option_a"))
    option_b = _parse_decree_option(data.get("option_b"))
    if option_a is None or option_b is None:
        return None

    debate_text = str(data.get("debate_text", "")).strip()
    if not debate_text:
        return None

    seen: set[str] = set()
    keywords: list[str] = []
    for item in (data.get("keywords") if isinstance(data.get("keywords"), list) else []):
        if not isinstance(item, str):
            continue
        kw = item.strip()
        if kw and kw not in seen:
            seen.add(kw)
            keywords.append(kw)
            if len(keywords) >= 5:
                break

    return DebateResult(
        debate_text=debate_text,
        minister_a=DebateMinister(
            name=minister_a.name, faction=minister_a.faction,
            position_summary=str(data.get("minister_a_position", "")).strip()[:50],
        ),
        minister_b=DebateMinister(
            name=minister_b.name, faction=minister_b.faction,
            position_summary=str(data.get("minister_b_position", "")).strip()[:50],
        ),
        option_a=option_a, option_b=option_b, keywords=keywords,
    )


def extract_json_object_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return text

    # Handle fenced output like ```json ... ```
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE).strip()

    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    for idx in range(start, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return text


def _coerce_decree_type(payload: dict) -> DecreeType | None:
    raw_type = payload.get("type")
    if isinstance(raw_type, DecreeType):
        return raw_type
    if isinstance(raw_type, str):
        try:
            return DecreeType(raw_type.strip())
        except ValueError:
            pass

    parts = []
    for key in ("type", "target", "sub_action"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip().lower())
    blob = " ".join(parts)
    if not blob:
        return None

    # tax
    if re.search(r"tax|税|赋|levy|taxation", blob):
        if re.search(r"increase|raise|add|加|增|higher|heavy", blob):
            return DecreeType.TAX_INCREASE
        if re.search(r"decrease|reduce|cut|免|减|降|lower", blob):
            return DecreeType.TAX_DECREASE
    if re.search(r"agricultur|farm|farming|民生|休养|减负|薄赋", blob):
        return DecreeType.TAX_DECREASE

    # military
    if re.search(r"recruit|conscript|enlist|raise.*troop|征兵|募兵|招兵|增兵", blob):
        return DecreeType.RECRUIT_TROOPS
    if re.search(r"disband|demobil|reduce.*troop|裁兵|裁军|遣散", blob):
        return DecreeType.DISBAND_TROOPS

    # policy domains
    if re.search(r"diplom|foreign|envoy|alliance|peace|外交|出使|遣使|议和", blob):
        return DecreeType.DIPLOMACY
    if re.search(r"disaster|relief|famine|flood|赈灾|赈济|救灾", blob):
        return DecreeType.DISASTER_RELIEF
    if re.search(r"harsh|punish|strict.*law|刑|峻法|重典|酷刑", blob):
        return DecreeType.HARSH_PUNISHMENT
    if re.search(r"personnel|appoint|dismiss|人事|任命|罢免|撤职|调任", blob):
        return DecreeType.PERSONNEL

    return None


def _coerce_personnel_action(payload: dict) -> PersonnelAction | None:
    raw = payload.get("sub_action")
    if isinstance(raw, PersonnelAction):
        return raw
    if isinstance(raw, str):
        try:
            return PersonnelAction(raw.strip())
        except ValueError:
            pass

    parts = []
    for key in ("type", "target", "sub_action"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip().lower())
    blob = " ".join(parts)
    if re.search(r"dismiss|remove|fire|罢免|撤职|免职|贬", blob):
        return PersonnelAction.DISMISS
    if re.search(r"appoint|promote|assign|任命|擢升|提拔", blob):
        return PersonnelAction.APPOINT
    return None


def _parse_decree_option(payload) -> StructuredDecree | None:
    if not isinstance(payload, dict):
        return None
    try:
        d = dict(payload)
        decree_type = _coerce_decree_type(d)
        if decree_type is None:
            return None

        target = d.get("target")
        if isinstance(target, str):
            target = target.strip() or None
        else:
            target = None

        sub_action = None
        if decree_type == DecreeType.PERSONNEL:
            sub_action = _coerce_personnel_action(d)

        params = d.get("parameters")
        if not isinstance(params, dict):
            params = None

        return StructuredDecree(
            type=decree_type,
            target=target,
            sub_action=sub_action,
            parameters=params,
        )
    except Exception:
        return None


def _validate_decrees(decrees: list[StructuredDecree]) -> list[StructuredDecree] | dict:
    validated = []
    for d in decrees:
        if d.type.value not in _VALID_DECREE_TYPES:
            return parse_error("无法识别为有效政令")
        validated.append(d)
    if not validated:
        return parse_error("无法识别为有效政令")
    return validated
