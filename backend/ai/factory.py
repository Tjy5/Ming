from __future__ import annotations

import os

from dotenv import load_dotenv

from .base import AIProvider
from .resilient import ResilientProvider

# Test-only provider registry: tests may register a deterministic fake here.
# The product itself has no bundled provider — playing requires a configured
# AI provider (API key etc.).
_PROVIDERS: dict[str, type[AIProvider]] = {}


def get_provider(name: str | None = None) -> AIProvider:
    if name is None:
        load_dotenv()
        name = os.getenv("AI_PROVIDER", "openai")

    normalized = (name or "").strip()
    lowered = normalized.lower()
    if lowered == "z":
        normalized = "Z"
    elif lowered in {"hotaru", "h"}:
        normalized = "h"
    elif lowered in {"openai", "google"}:
        normalized = lowered

    if normalized == "openai":
        from .openai_provider import OpenAIProvider

        return ResilientProvider(OpenAIProvider())

    if normalized == "google":
        from .google_provider import GoogleProvider

        return ResilientProvider(GoogleProvider())

    if normalized == "h":
        from .h_provider import HProvider

        return ResilientProvider(HProvider())

    if normalized == "Z":
        from .z_provider import ZProvider

        return ResilientProvider(ZProvider())

    cls = _PROVIDERS.get(normalized)
    if cls is not None:
        return ResilientProvider(cls())

    # Fallback to provider based on user selected provider_type (default OpenAI)
    prefix = normalized.upper().replace("-", "_").replace(" ", "_")
    provider_type = os.getenv(f"{prefix}_PROVIDER_TYPE", "openai").lower()

    if provider_type in {"google", "gemini"}:
        from .google_provider import GoogleProvider
        return ResilientProvider(GoogleProvider(prefix=prefix))

    if provider_type == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return ResilientProvider(AnthropicProvider(prefix=prefix))

    if provider_type == "openai-response":
        from .openai_response_provider import OpenAIResponseProvider
        return ResilientProvider(OpenAIResponseProvider(prefix=prefix))

    from .openai_provider import OpenAIProvider
    return ResilientProvider(OpenAIProvider(prefix=prefix))
