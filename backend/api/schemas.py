from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from models.game import (
    ErrorResponse,
    GameState,
    HistoryEntry,
    Minister,
    MinisterReaction,
    StructuredDecree,
)
from models.settlement import SettlementCommitResult

MAX_FREE_TEXT_LENGTH = 200


class DecreeRequest(BaseModel):
    decrees: list[StructuredDecree] = Field(default_factory=list)
    free_text: str | None = None
    source_script_id: str | None = None
    loyalty_effects: list[tuple[str, int]] | None = None
    # int = 数值增量；str = 枚举字段直设（region.*.threat/control，史实威胁清除）。
    # 与 models/game.py EventChoice / api/admin_routes.py AdminScriptChoice 同步放宽
    # （脚本事件 choice 的 state_effects 原样回传，校验不匹配会 422）。
    state_effects: dict[str, int | str] | None = None


class ParseRequest(BaseModel):
    text: str


class GameStateResponse(GameState):
    history_total_count: int | None = None


class AdvanceMonthResponse(BaseModel):
    state: GameState
    triggered_events: list[str] = Field(default_factory=list)
    game_over: dict | None = None
    new_ministers: list[Minister] = Field(default_factory=list)


class ActionExecutionResponse(BaseModel):
    state: GameState
    result: SettlementCommitResult


class ActionErrorEnvelope(BaseModel):
    detail: ErrorResponse


class HistoryPage(BaseModel):
    total: int
    offset: int
    limit: int
    entries: list[HistoryEntry] = Field(default_factory=list)


class DebateSilenceResponse(BaseModel):
    state: GameState
    prestige_change: int


class MemorialResolveResponse(BaseModel):
    state: GameState
    action: str
    narrative: str | None = None
    delta: dict | None = None
    minister_reactions: list[MinisterReaction] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_FREE_TEXT_LENGTH)


class SaveRequest(BaseModel):
    name: str | None = None


class DebateStartRequest(BaseModel):
    category: str
    topic: str





class MemorialResolveRequest(BaseModel):
    action: str


class ConveneAssemblyRequest(BaseModel):
    topic: str
    decree_type: str


class AdoptSuggestionRequest(BaseModel):
    suggestion_index: int


class AssemblyDebateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=80)
    decree_type: str | None = None


class AssemblyVoteRequest(BaseModel):
    decree_type: str | None = None


class AssemblyDecreeRequest(BaseModel):
    decision: str


class AssemblyRageRequest(BaseModel):
    target_faction: str


ThinkingConfigValue = str | bool | int


class AISettingsDraft(BaseModel):
    provider: str
    provider_type: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    simple_model: str | None = None
    enable_thinking: bool | None = None
    enable_thinking_simple: bool | None = None
    thinking_config: dict[str, ThinkingConfigValue] | None = None
    thinking_config_simple: dict[str, ThinkingConfigValue] | None = None


class AISettingsRequest(AISettingsDraft):
    """Legacy schema name retained for generated-client compatibility."""


class AISettingsTestRequest(AISettingsDraft):
    pass


class AISettingsAssessmentRequest(AISettingsDraft):
    pass


class AISettingsApplyRequest(AISettingsDraft):
    verification_token: str = Field(min_length=16, max_length=256)


class AISettingsVerifiedConfig(BaseModel):
    provider: str
    provider_type: str
    base_url: str
    model: str
    simple_model: str | None = None
    enable_thinking: bool
    enable_thinking_simple: bool
    thinking_config: dict[str, ThinkingConfigValue] | None = None
    thinking_config_simple: dict[str, ThinkingConfigValue] | None = None


class AISettingsTestResponse(BaseModel):
    ok: Literal[True] = True
    message: str
    latency_ms: int
    request_id: str
    verification_token: str
    expires_at: str
    verified_config: AISettingsVerifiedConfig


class AISettingsAssessmentItem(BaseModel):
    scenario: Literal[
        "structured_schema",
        "state_grounding",
        "causal_adjudication",
        "short_memory",
    ]
    status: Literal["pass", "warn", "fail"]
    explanation: str


class AISettingsTokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int


class AISettingsAssessmentSummary(BaseModel):
    tier: Literal["excellent", "usable", "high_risk", "unassessed"]
    results: list[AISettingsAssessmentItem] = Field(default_factory=list)
    calls_completed: int = 0
    usage: AISettingsTokenUsage | None = None
    assessed_at: str | None = None
    validator_version: str | None = None
    stopped_by_transport: bool = False
    config_matches: bool = True


class AISettingsAssessmentResponse(AISettingsAssessmentSummary):
    request_id: str


class AISettingsErrorEnvelope(BaseModel):
    detail: ErrorResponse


class AISettingsResponse(AISettingsDraft):
    provider: str
    provider_type: str
    api_key: str
    base_url: str
    model: str
    simple_model: str | None = None
    enable_thinking: bool = False
    enable_thinking_simple: bool = False
    provider_options: list[str] = Field(default_factory=list)
    sources: dict[str, str] = Field(default_factory=dict)
    effective: bool = False
    status: Literal["effective", "configuration_required", "configuration_invalid"]
    assessment: AISettingsAssessmentSummary | None = None


class AIModelListRequest(BaseModel):
    provider: str | None = None
    provider_type: str | None = None
    api_key: str | None = None
    base_url: str | None = None


class AIModelListResponse(BaseModel):
    provider: str
    models: list[str] = Field(default_factory=list)
    source: str


class SettingsRequest(BaseModel):
    rule_parse_fallback: bool
