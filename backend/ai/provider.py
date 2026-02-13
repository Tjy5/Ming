from __future__ import annotations

import abc
import asyncio
import os
import re

from models.game import GameState, StructuredDecree
from models.enums import DecreeType, PersonnelAction


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
            return {"error": "检测到否定指令，请直接描述您想执行的政令"}
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
            return {"error": "无法识别具体政令，请使用按钮操作或描述具体政令内容"}
        return results

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        return REJECTION_TEMPLATES.get(decree.type, f"陛下，此令无法执行：{reason}")


# ── Factory ──────────────────────────────────────────────

_PROVIDERS: dict[str, type[AIProvider]] = {"mock": MockProvider}

_VALID_DECREE_TYPES = {t.value for t in DecreeType}


def get_provider(name: str | None = None) -> AIProvider:
    if name is None:
        name = os.getenv("AI_PROVIDER", "mock")
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown AI provider: {name}")
    return ResilientProvider(cls())


# ── Timeout / Retry / Validation Wrapper ─────────────────

class ResilientProvider(AIProvider):
    """Wraps any AIProvider with timeout, retry, and output validation."""

    def __init__(self, inner: AIProvider, timeout: float = 10.0, retries: int = 3):
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
            except Exception:
                if attempt == self._retries - 1:
                    return "（AI服务暂时不可用，数值已更新）"
        return "（AI服务暂时不可用，数值已更新）"

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
                    return result
                return _validate_decrees(result)
            except Exception:
                if attempt == self._retries - 1:
                    return {"error": "AI解析服务暂时不可用，请使用按钮操作"}
        return {"error": "AI解析服务暂时不可用，请使用按钮操作"}

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        for attempt in range(self._retries):
            try:
                return await asyncio.wait_for(
                    self._inner.rejection_narrative(decree, reason),
                    timeout=self._timeout,
                )
            except Exception:
                if attempt == self._retries - 1:
                    return f"此令无法执行：{reason}"
        return f"此令无法执行：{reason}"


def _validate_decrees(decrees: list[StructuredDecree]) -> list[StructuredDecree] | dict:
    validated = []
    for d in decrees:
        if d.type.value not in _VALID_DECREE_TYPES:
            return {"error": "无法识别为有效政令"}
        validated.append(d)
    if not validated:
        return {"error": "无法识别为有效政令"}
    return validated
