from __future__ import annotations

"""Backward-compatible exports for AI provider modules.

This module intentionally re-exports symbols that were historically defined in
`ai.provider`, while implementation is split across smaller modules.
"""

from .base import (
    AIProvider,
    PARSE_ERROR_TYPE_PARSE,
    PARSE_ERROR_TYPE_UNAVAILABLE,
    get_rule_parse_fallback,
    infer_decree_type_from_topic,
    parse_error,
    set_rule_parse_fallback,
)
from .factory import get_provider
from .mock_provider import (
    DIPLOMACY_KEYWORDS,
    EXECUTION_PREFIX_RE,
    EXECUTION_SUFFIX_RE,
    KEYWORD_MAP,
    MockProvider,
    NEGATION_KEYWORDS,
    NARRATIVE_TEMPLATES,
    PERSON_PATTERN,
    REGION_KEYWORDS,
    REJECTION_TEMPLATES,
)
from .parsers import (
    DEBATE_SYSTEM_PROMPT,
    _FREEFORM_SYSTEM_PROMPT,
    _validate_decrees,
    build_debate_prompt,
    build_freeform_user_prompt,
    extract_json_object_text,
    parse_debate_response,
    parse_decree_response,
    parse_freeform_response,
    parse_memorial_draft,
    validate_memorial_decrees,
)
from .resilient import ResilientProvider

_rule_parse_fallback_enabled = get_rule_parse_fallback()

__all__ = [
    "AIProvider",
    "DEBATE_SYSTEM_PROMPT",
    "DIPLOMACY_KEYWORDS",
    "EXECUTION_PREFIX_RE",
    "EXECUTION_SUFFIX_RE",
    "KEYWORD_MAP",
    "MockProvider",
    "NARRATIVE_TEMPLATES",
    "NEGATION_KEYWORDS",
    "PARSE_ERROR_TYPE_PARSE",
    "PARSE_ERROR_TYPE_UNAVAILABLE",
    "PERSON_PATTERN",
    "REGION_KEYWORDS",
    "REJECTION_TEMPLATES",
    "ResilientProvider",
    "_FREEFORM_SYSTEM_PROMPT",
    "_rule_parse_fallback_enabled",
    "_validate_decrees",
    "build_debate_prompt",
    "build_freeform_user_prompt",
    "extract_json_object_text",
    "get_provider",
    "get_rule_parse_fallback",
    "infer_decree_type_from_topic",
    "parse_debate_response",
    "parse_decree_response",
    "parse_error",
    "parse_freeform_response",
    "parse_memorial_draft",
    "set_rule_parse_fallback",
    "validate_memorial_decrees",
]
