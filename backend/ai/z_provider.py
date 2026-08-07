from __future__ import annotations

import os
from typing import Any
import httpx
import openai
from dotenv import load_dotenv

from .openai_provider import OpenAIProvider

load_dotenv()


def _read_required_openai_config(
    api_key_env: str,
    base_url_env: str,
    error_message: str,
) -> tuple[str, str]:
    api_key = (os.getenv(api_key_env) or "").strip()
    base_url = (os.getenv(base_url_env) or "").strip()
    if not api_key or not base_url:
        raise ValueError(error_message)
    return api_key, base_url


class ZProvider(OpenAIProvider):
    def __init__(self):
        super().__init__()
        
        trust_env_proxy = os.getenv("OPENAI_TRUST_ENV_PROXY", "0").lower() in ("1", "true", "yes", "on")
        http_client = httpx.AsyncClient(trust_env=trust_env_proxy)

        api_key, base_url = _read_required_openai_config(
            "Z_API_KEY",
            "Z_BASE_URL",
            "Z_API_KEY and Z_BASE_URL must be set in .env",
        )

        # Clean base_url if it contains /chat/completions
        if base_url and base_url.endswith("/chat/completions"):
            base_url = base_url.replace("/chat/completions", "")
        
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            default_headers={"User-Agent": "Mozilla/5.0 (compatible; YuanmingSimulator/1.0)"},
        )
        self.model = os.getenv("Z_MODEL", "qwen3.5-plus-2026-02-15")
        self._configure_task_models(
            "Z",
            parse_default=self.model,
            freeform_default=self.model,
            turn_commentary_default=self.model,
            use_simple_for_parse=False,
            use_simple_for_freeform=False,
            use_simple_for_turn_commentary=False,
        )
        self._enable_thinking_default = os.getenv("Z_ENABLE_THINKING_DEFAULT", "0").lower() in (
            "1", "true", "yes", "on",
        )
        raw_tasks = os.getenv("Z_ENABLE_THINKING_TASKS")
        if raw_tasks is None:
            self._enable_thinking_tasks = {
                "generate_debate_narrative",
                "generate_memorial",
                "generate_assembly_debate",
            }
        else:
            self._enable_thinking_tasks = {
                task.strip() for task in raw_tasks.split(",") if task.strip()
            }

    def _chat_completion_extra_kwargs(
        self,
        *,
        task_name: str,
        model: str,
    ) -> dict[str, Any]:
        # Z-specific: per-task thinking list + default toggle
        z_enable = self._enable_thinking_default or (
            task_name in self._enable_thinking_tasks
        )
        # Also consider parent's UI-driven enable_thinking toggle
        parent_enable = self._enable_thinking
        enable_thinking = z_enable or parent_enable
        return {"extra_body": {"enable_thinking": enable_thinking}}
