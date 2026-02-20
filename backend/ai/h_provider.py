from __future__ import annotations

import os
import httpx
import openai
from dotenv import load_dotenv

from .openai_provider import OpenAIProvider

load_dotenv()


def _read_required_openai_config(
    api_key_env: str,
    base_url_env: str,
    fallback_api_key_env: str | None,
    fallback_base_url_env: str | None,
    error_message: str,
) -> tuple[str, str]:
    api_key = (os.getenv(api_key_env) or (os.getenv(fallback_api_key_env) if fallback_api_key_env else "") or "").strip()
    base_url = (os.getenv(base_url_env) or (os.getenv(fallback_base_url_env) if fallback_base_url_env else "") or "").strip()
    if not api_key or not base_url:
        raise ValueError(error_message)
    return api_key, base_url


class HProvider(OpenAIProvider):
    def __init__(self):
        # Initialize OpenAIProvider but override the client with Hotaru settings
        super().__init__()
        
        # Override the client and model with Hotaru specific configuration
        trust_env_proxy = os.getenv("OPENAI_TRUST_ENV_PROXY", "0").lower() in ("1", "true", "yes", "on")
        http_client = httpx.AsyncClient(trust_env=trust_env_proxy)

        api_key, base_url = _read_required_openai_config(
            "H_API_KEY",
            "H_BASE_URL",
            "HOTARU_API_KEY",
            "HOTARU_BASE_URL",
            "H_API_KEY and H_BASE_URL must be set in .env",
        )

        # Hotaru may block OpenAI SDK default UA; allow override and keep a safe default.
        user_agent = (
            os.getenv("H_USER_AGENT")
            or os.getenv("HOTARU_USER_AGENT")
            or "Mozilla/5.0 (compatible; ChongzhenSimulator/1.0)"
        )
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            default_headers={"User-Agent": user_agent},
        )
        self.model = os.getenv("H_MODEL") or os.getenv("HOTARU_MODEL", "gemini-3-pro-preview")
        self._configure_task_models("HOTARU")
