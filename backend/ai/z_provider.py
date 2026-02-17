from __future__ import annotations

import os
import httpx
import openai
from dotenv import load_dotenv

from .openai_provider import OpenAIProvider

load_dotenv()

class ZProvider(OpenAIProvider):
    def __init__(self):
        super().__init__()
        
        trust_env_proxy = os.getenv("OPENAI_TRUST_ENV_PROXY", "0").lower() in ("1", "true", "yes", "on")
        http_client = httpx.AsyncClient(trust_env=trust_env_proxy)
        
        api_key = os.getenv("Z_API_KEY")
        base_url = os.getenv("Z_BASE_URL")
        
        if not api_key or not base_url:
            # Fallback to hardcoded values if not in env, as requested by user in prompt
            # But normally we expect them in env. I will write them to env later.
            # For now, let's allow them to be None and rely on .env being updated.
            pass

        # Clean base_url if it contains /chat/completions
        if base_url and base_url.endswith("/chat/completions"):
            base_url = base_url.replace("/chat/completions", "")
        
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            default_headers={"User-Agent": "Mozilla/5.0 (compatible; ChongzhenSimulator/1.0)"},
        )
        self.model = os.getenv("Z_MODEL", "qwen3.5-plus-2026-02-15")
        self._configure_task_models(
            "Z",
            parse_default="qwen3-omni-flash-2025-12-01",
            freeform_default=self.model,
            turn_commentary_default="qwen3-omni-flash-2025-12-01",
            use_simple_for_freeform=False,
        )
