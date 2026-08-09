from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from .base import AIProvider
from .config import (
    AIProviderConfig,
    config_from_environment,
    load_effective_ai_config,
    normalize_provider_name,
)
from .endpoint_security import Resolver, create_safe_async_client
from .resilient import ResilientProvider


# Tests may register deterministic providers here.  Product code never adds a
# provider to this registry and therefore cannot silently obtain a free/default
# model through it.
_PROVIDERS: dict[str, type[AIProvider]] = {}


@dataclass(frozen=True, slots=True)
class AttemptPolicy:
    name: str
    timeout: float | None
    retries: int | None
    sdk_max_retries: int


RUNTIME = AttemptPolicy(
    name="runtime-v1",
    timeout=None,
    retries=None,
    sdk_max_retries=2,
)
SINGLE_ATTEMPT = AttemptPolicy(
    name="settings-single-attempt-v1",
    timeout=15.0,
    retries=1,
    sdk_max_retries=0,
)


def build_provider(
    config: AIProviderConfig,
    attempt_policy: AttemptPolicy = RUNTIME,
    *,
    resolver: Resolver | None = None,
) -> ResilientProvider:
    """Build one provider from an explicit canonical config with no env reads."""

    registered = _PROVIDERS.get(config.provider)
    if registered is not None:
        return ResilientProvider(
            registered(),
            timeout=attempt_policy.timeout,
            retries=attempt_policy.retries,
        )

    http_client = create_safe_async_client(
        config.base_url,
        resolver=resolver,
        timeout=attempt_policy.timeout or 120.0,
    )
    common = {
        "api_key": config.api_key,
        "base_url": config.base_url,
        "model": config.model,
        "simple_model": config.simple_model,
        "enable_thinking": config.enable_thinking,
        "enable_thinking_simple": config.enable_thinking_simple,
        "thinking_config": config.thinking_config,
        "thinking_config_simple": config.thinking_config_simple,
        "http_client": http_client,
        "sdk_max_retries": attempt_policy.sdk_max_retries,
        "use_environment": False,
    }

    if config.provider == "google" or config.provider_type == "google":
        from .google_provider import GoogleProvider

        inner: AIProvider = GoogleProvider(prefix="GOOGLE", **common)
    elif config.provider == "h":
        from .h_provider import HProvider

        inner = HProvider(**common)
    elif config.provider == "Z":
        from .z_provider import ZProvider

        inner = ZProvider(**common)
    elif config.provider_type == "anthropic":
        from .anthropic_provider import AnthropicProvider

        inner = AnthropicProvider(prefix=_prefix(config.provider), **common)
    elif config.provider_type == "openai-response":
        from .openai_response_provider import OpenAIResponseProvider

        inner = OpenAIResponseProvider(prefix=_prefix(config.provider), **common)
    else:
        from .openai_provider import OpenAIProvider

        inner = OpenAIProvider(prefix=_prefix(config.provider), **common)

    return ResilientProvider(
        inner,
        timeout=attempt_policy.timeout,
        retries=attempt_policy.retries,
    )


def _prefix(provider: str) -> str:
    if provider == "h":
        return "HOTARU"
    return provider.upper().replace("-", "_").replace(" ", "_")


def get_provider(name: str | None = None) -> AIProvider:
    """Compatibility entry point; runtime without a name requires proof."""

    load_dotenv()
    raw_name = name if name is not None else os.getenv("AI_PROVIDER")
    normalized = normalize_provider_name(raw_name)
    registered = _PROVIDERS.get(normalized)
    if registered is not None:
        return ResilientProvider(registered())
    config = (
        config_from_environment(provider_name=normalized)
        if name is not None
        else load_effective_ai_config()
    )
    return build_provider(config, RUNTIME)
