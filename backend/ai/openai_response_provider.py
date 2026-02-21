from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
from dotenv import load_dotenv

from .openai_provider import OpenAIProvider, _env_bool

load_dotenv()

logger = logging.getLogger(__name__)


class OpenAIResponseProvider(OpenAIProvider):
    """Provider that uses OpenAI's Responses API instead of Chat Completions.

    The Responses API uses ``/responses`` endpoint with ``input`` instead of
    ``/chat/completions`` with ``messages``.  Output uses ``output_text``
    instead of ``choices[0].message.content``.

    This provider inherits all prompt-building logic from OpenAIProvider and
    only overrides ``_chat_completion_with_fallback`` to route through the
    Responses API endpoint.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        prefix: str = "OPENAI",
    ):
        super().__init__(api_key=api_key, base_url=base_url, model=model, prefix=prefix)

        actual_api_key = api_key or os.getenv(f"{prefix}_API_KEY")
        actual_base_url = base_url or os.getenv(f"{prefix}_BASE_URL") or "https://api.openai.com/v1"
        actual_base_url = actual_base_url.rstrip("/")
        # Strip trailing /chat/completions if present
        for suffix in ("/chat/completions", "/v1"):
            if actual_base_url.endswith(suffix):
                actual_base_url = actual_base_url[: -len(suffix)]
                break

        self._responses_base_url = actual_base_url
        self._responses_api_key = actual_api_key or ""
        trust_env = _env_bool(f"{prefix}_TRUST_ENV_PROXY", False)
        if not trust_env and prefix != "OPENAI":
            trust_env = _env_bool("OPENAI_TRUST_ENV_PROXY", False)
        self._http = httpx.AsyncClient(trust_env=trust_env, timeout=120.0)

    # ── Core Responses API helpers ─────────────────────────

    def _build_responses_body(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        top_p: float | None = None,
        response_format: dict[str, str] | None = None,
        extra_body: dict | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Build the JSON body for a Responses API request."""
        body: dict[str, Any] = {
            "model": model,
            "input": messages,
        }
        if stream:
            body["stream"] = True
        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p
        if response_format is not None:
            fmt_type = response_format.get("type")
            if fmt_type == "json_object":
                body["text"] = {"format": {"type": "json_object"}}
        if extra_body:
            body.update(extra_body)
        return body

    def _responses_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._responses_api_key}",
            "Content-Type": "application/json",
        }

    # ── Core Responses API call ──────────────────────────

    async def _responses_create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        top_p: float | None = None,
        response_format: dict[str, str] | None = None,
        extra_body: dict | None = None,
    ) -> str:
        """Call the OpenAI Responses API and return the output text."""
        url = f"{self._responses_base_url}/v1/responses"
        body = self._build_responses_body(
            model=model, messages=messages,
            temperature=temperature, top_p=top_p,
            response_format=response_format, extra_body=extra_body,
        )

        response = await self._http.post(url, headers=self._responses_headers(), json=body)
        response.raise_for_status()
        data = response.json()

        # Primary: use output_text field
        output_text = data.get("output_text")
        if output_text:
            return output_text

        # Fallback: iterate output items
        for item in data.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        return content.get("text", "")
        return ""

    # ── Streaming Responses API call ─────────────────────

    async def _responses_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        top_p: float | None = None,
        extra_body: dict | None = None,
    ) -> AsyncIterator[str]:
        """Stream text deltas from the Responses API via SSE."""
        url = f"{self._responses_base_url}/v1/responses"
        body = self._build_responses_body(
            model=model, messages=messages,
            temperature=temperature, top_p=top_p,
            extra_body=extra_body, stream=True,
        )

        async with self._http.stream(
            "POST", url, headers=self._responses_headers(), json=body,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                # Handle output_text delta events
                event_type = event.get("type", "")
                if event_type == "response.output_text.delta":
                    delta = event.get("delta", "")
                    if delta:
                        yield delta

    # ── Override the key completion method ────────────────

    async def _chat_completion_with_fallback(
        self,
        *,
        task_name: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        top_p: float | None = None,
        response_format: dict[str, str] | None = None,
    ) -> Any:
        """Override to use Responses API instead of Chat Completions."""
        kwargs = self._build_chat_completion_kwargs(
            task_name=task_name,
            model=model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            response_format=response_format,
        )

        extra_body = kwargs.pop("extra_body", None)
        resolved_temp = kwargs.get("temperature", temperature)
        resolved_top_p = kwargs.get("top_p")
        resolved_format = kwargs.get("response_format")

        try:
            text = await self._responses_create(
                model=model,
                messages=messages,
                temperature=resolved_temp,
                top_p=resolved_top_p,
                response_format=resolved_format,
                extra_body=extra_body,
            )
            return _fake_response(text)
        except Exception as first_error:
            if model == self.model:
                raise
            logger.warning(
                "%s model %s failed (%s), fallback to %s",
                task_name,
                model,
                type(first_error).__name__,
                self.model,
            )
            text = await self._responses_create(
                model=self.model,
                messages=messages,
                temperature=resolved_temp,
                top_p=resolved_top_p,
                response_format=resolved_format,
                extra_body=extra_body,
            )
            return _fake_response(text)

    async def stream_narrative(
        self, delta_attribution: dict, game_state, chain_events: list[str], decree,
    ) -> AsyncIterator[str]:
        """Stream narrative via Responses API SSE, fallback to non-stream."""
        from .prompts import NARRATIVE_SYSTEM_PROMPT, build_narrative_prompt as _build_narrative_prompt

        prompt = _build_narrative_prompt(delta_attribution, game_state, chain_events, decree)
        messages = [
            {"role": "system", "content": NARRATIVE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        kwargs = self._build_chat_completion_kwargs(
            task_name="generate_narrative",
            model=self.model,
            messages=messages,
            temperature=0.7,
        )
        extra_body = kwargs.pop("extra_body", None)
        resolved_temp = kwargs.get("temperature", 0.7)
        resolved_top_p = kwargs.get("top_p")

        emitted_any = False
        try:
            async for chunk in self._responses_stream(
                model=self.model,
                messages=messages,
                temperature=resolved_temp,
                top_p=resolved_top_p,
                extra_body=extra_body,
            ):
                emitted_any = True
                yield chunk
            return
        except Exception as e:
            logger.error("Error streaming narrative via Responses API: %s", e)
        if emitted_any:
            return
        fallback = await self.generate_narrative(
            delta_attribution, game_state, chain_events, decree,
        )
        if fallback:
            yield fallback


def _fake_response(text: str) -> SimpleNamespace:
    """Build an object matching ``response.choices[0].message.content``."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=text))
        ]
    )
