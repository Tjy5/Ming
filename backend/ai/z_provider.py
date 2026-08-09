from __future__ import annotations

import os
from typing import Any, Mapping

import httpx
import openai  # compatibility: tests patch the historical module-level SDK handle
from dotenv import load_dotenv

from .openai_provider import OpenAIProvider

load_dotenv()


class ZProvider(OpenAIProvider):
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
            api_key = api_key or os.getenv("Z_API_KEY")
            base_url = base_url or os.getenv("Z_BASE_URL")
            model = model or os.getenv("Z_MODEL", "qwen3.5-plus-2026-02-15")
            if enable_thinking is None:
                enable_thinking = os.getenv("OPENAI_ENABLE_THINKING", "0").lower() in {
                    "1", "true", "yes", "on",
                }
            if enable_thinking_simple is None:
                enable_thinking_simple = os.getenv(
                    "OPENAI_ENABLE_THINKING_SIMPLE",
                    "0",
                ).lower() in {"1", "true", "yes", "on"}
        if not api_key or not base_url:
            raise ValueError("Z API Key and Base URL are required")
        base_url = base_url.removesuffix("/chat/completions").rstrip("/")
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            prefix="Z",
            simple_model=simple_model,
            enable_thinking=enable_thinking,
            enable_thinking_simple=enable_thinking_simple,
            thinking_config=thinking_config,
            thinking_config_simple=thinking_config_simple,
            http_client=http_client,
            sdk_max_retries=sdk_max_retries,
            default_headers={
                "User-Agent": "Mozilla/5.0 (compatible; YuanmingSimulator/1.0)",
            },
            use_environment=use_environment,
        )
        self._configure_task_models(
            "Z",
            parse_default=self.model,
            freeform_default=self.model,
            turn_commentary_default=self.model,
            use_simple_for_parse=False,
            use_simple_for_freeform=False,
            use_simple_for_turn_commentary=False,
        )
        self._enable_thinking_default = (
            use_environment
            and os.getenv("Z_ENABLE_THINKING_DEFAULT", "0").lower() in {"1", "true", "yes", "on"}
        )
        raw_tasks = os.getenv("Z_ENABLE_THINKING_TASKS") if use_environment else ""
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
        enable_thinking = self._enable_thinking_default or (
            task_name in self._enable_thinking_tasks
        ) or self._enable_thinking
        if not self._use_environment:
            explicit = super()._chat_completion_extra_kwargs(task_name=task_name, model=model)
            if explicit:
                return explicit
        return {"extra_body": {"enable_thinking": enable_thinking}}
