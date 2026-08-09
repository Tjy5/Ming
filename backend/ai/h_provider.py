from __future__ import annotations

import os
from typing import Any, Mapping

import httpx
import openai  # compatibility: tests patch the historical module-level SDK handle
from dotenv import load_dotenv

from .openai_provider import OpenAIProvider

load_dotenv()


class HProvider(OpenAIProvider):
    """Hotaru OpenAI-compatible provider without a throwaway parent client."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        *,
        simple_model: str | None = None,
        enable_thinking: bool | None = None,
        enable_thinking_simple: bool | None = None,
        thinking_config: Mapping[str, Any] | None = None,
        thinking_config_simple: Mapping[str, Any] | None = None,
        http_client: httpx.AsyncClient | None = None,
        sdk_max_retries: int | None = None,
        use_environment: bool = True,
    ) -> None:
        if use_environment:
            api_key = api_key or os.getenv("H_API_KEY") or os.getenv("HOTARU_API_KEY")
            base_url = base_url or os.getenv("H_BASE_URL") or os.getenv("HOTARU_BASE_URL")
            model = model or os.getenv("H_MODEL") or os.getenv(
                "HOTARU_MODEL",
                "gemini-3-pro-preview",
            )
        if not api_key or not base_url:
            raise ValueError("Hotaru API Key and Base URL are required")
        user_agent = (
            (os.getenv("H_USER_AGENT") or os.getenv("HOTARU_USER_AGENT"))
            if use_environment
            else None
        ) or "Mozilla/5.0 (compatible; YuanmingSimulator/1.0)"
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            prefix="HOTARU",
            simple_model=simple_model,
            enable_thinking=enable_thinking,
            enable_thinking_simple=enable_thinking_simple,
            thinking_config=thinking_config,
            thinking_config_simple=thinking_config_simple,
            http_client=http_client,
            sdk_max_retries=sdk_max_retries,
            default_headers={"User-Agent": user_agent},
            use_environment=use_environment,
        )
