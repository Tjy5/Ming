from __future__ import annotations

from pydantic import BaseModel, Field

from models.game import StructuredDecree

MAX_FREE_TEXT_LENGTH = 200


class DecreeRequest(BaseModel):
    decrees: list[StructuredDecree] = Field(default_factory=list)
    free_text: str | None = None
    source_script_id: str | None = None
    loyalty_effects: list[tuple[str, int]] | None = None
    state_effects: dict[str, int] | None = None


class ParseRequest(BaseModel):
    text: str


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


class AISettingsRequest(BaseModel):
    provider: str
    provider_type: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    simple_model: str | None = None
    enable_thinking: bool | None = None
    enable_thinking_simple: bool | None = None
    thinking_config: dict[str, str | bool | int] | None = None
    thinking_config_simple: dict[str, str | bool | int] | None = None


class AIModelListRequest(BaseModel):
    provider: str | None = None
    provider_type: str | None = None
    api_key: str | None = None
    base_url: str | None = None


class SettingsRequest(BaseModel):
    rule_parse_fallback: bool
