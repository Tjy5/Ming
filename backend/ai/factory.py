from __future__ import annotations

import os

from dotenv import load_dotenv

from .base import AIProvider
from .mock_provider import MockProvider
from .resilient import ResilientProvider

_PROVIDERS: dict[str, type[AIProvider]] = {
    "mock": MockProvider,
}


def get_provider(name: str | None = None) -> AIProvider:
    if name is None:
        load_dotenv()
        name = os.getenv("AI_PROVIDER", "mock")

    normalized = (name or "").strip()
    lowered = normalized.lower()
    if lowered == "z":
        normalized = "Z"
    elif lowered in {"hotaru", "h"}:
        normalized = "h"
    elif lowered in {"openai", "google", "mock"}:
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
    if cls is None:
        raise ValueError(f"Unknown AI provider: {normalized}")
    return ResilientProvider(cls())

