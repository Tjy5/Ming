from __future__ import annotations

import os
import httpx
import openai
from dotenv import load_dotenv

from .openai_provider import OpenAIProvider

load_dotenv()

class HProvider(OpenAIProvider):
    def __init__(self):
        # Initialize OpenAIProvider but override the client with Hotaru settings
        super().__init__()
        
        # Override the client and model with Hotaru specific configuration
        trust_env_proxy = os.getenv("OPENAI_TRUST_ENV_PROXY", "0").lower() in ("1", "true", "yes", "on")
        http_client = httpx.AsyncClient(trust_env=trust_env_proxy)
        
        api_key = os.getenv("HOTARU_API_KEY")
        base_url = os.getenv("HOTARU_BASE_URL")
        
        if not api_key or not base_url:
            raise ValueError("HOTARU_API_KEY and HOTARU_BASE_URL must be set in .env")

        # Hotaru may block OpenAI SDK default UA; allow override and keep a safe default.
        user_agent = os.getenv(
            "HOTARU_USER_AGENT",
            "Mozilla/5.0 (compatible; ChongzhenSimulator/1.0)",
        )
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            default_headers={"User-Agent": user_agent},
        )
        self.model = os.getenv("HOTARU_MODEL", "gemini-3-pro-preview")
        self._configure_task_models("HOTARU")
