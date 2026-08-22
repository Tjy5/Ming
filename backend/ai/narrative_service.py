"""The only generate -> validate -> persist -> display narrative pipeline."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from time import perf_counter
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from ai.narrative_context import NarrativeContext, project_narrative_context_for_prompt
from ai.narrative_registry import get_narrative_path
from ai.narrative_validators import (
    NarrativeFinding,
    build_repair_instruction,
    facts_narrative,
    sanitize_candidate,
    sentence_chunks,
    validate_narrative_candidate,
)
from db.narrative_memory import NarrativeArtifactRecord, save_artifact
from models.game import GameState


NarrativeGenerate = Callable[[NarrativeContext, str | None], Awaitable[str]]
NarrativeStream = Callable[[NarrativeContext], AsyncIterator[str]]
NarrativeRuleFallback = Callable[[NarrativeContext], str | Awaitable[str] | None]


class NarrativeGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path_id: str
    context_version_id: UUID | None = None
    settlement_id: UUID | None = None
    narrative_status: Literal[
        "validated", "repaired", "sanitized", "fallback_facts",
    ]
    text: str = Field(min_length=1)
    chunks: list[str] = Field(min_length=1)
    finding_codes: list[str] = Field(default_factory=list)
    attempt_count: int = Field(strict=True, ge=1, le=2)
    request_id: str
    artifact_id: UUID | None = None
    progress_stages: list[
        Literal["context_ready", "generating", "validating", "repairing", "validated"]
    ] = Field(default_factory=list)
    context_schema_version: str = "narrative-context-v1"
    source_versions: dict[str, str] = Field(default_factory=dict)
    outcome_stage: Literal[
        "validated", "repaired", "sanitized", "fallback_facts",
    ]
    duration_ms: int = Field(default=0, ge=0)


def build_narrative_prompt(
    context: NarrativeContext,
    repair_instruction: str | None = None,
) -> tuple[str, str]:
    """Render the typed context without logging or persisting raw prompts."""

    system = (
        "你是元末至正时代的开放沙盒世界叙事者，以后世洪武皇帝朱元璋及其开国"
        "臣僚的历史视角叙事。只描述 NARRATIVE_CONTEXT 中当前版本和已提交"
        "结算的事实；正史不是标准答案。不得输出隐藏推理、未落库变化或未来完成结果。"
    )
    prompt_context = project_narrative_context_for_prompt(context)
    prompt = (
        "请生成简洁、因果连续、可继续行动的中文叙事。\n"
        f"NARRATIVE_CONTEXT={prompt_context.prompt_json()}"
    )
    if repair_instruction:
        prompt += "\nREPAIR_REQUIREMENTS=" + repair_instruction
    return prompt, system


def runtime_generator(provider) -> NarrativeGenerate:
    async def _generate(
        context: NarrativeContext,
        repair_instruction: str | None,
    ) -> str:
        if provider is None:
            raise RuntimeError("runtime provider unavailable")
        prompt, system = build_narrative_prompt(context, repair_instruction)
        result = await provider.generate_text_once(
            prompt,
            system_prompt=system,
            max_output_tokens=700,
        )
        return result.text

    return _generate


def runtime_rule_fallback(provider) -> NarrativeRuleFallback | None:
    handler = getattr(provider, "configured_narrative_fallback", None)
    if not callable(handler):
        return None

    async def _fallback(context: NarrativeContext) -> str | None:
        value = handler(context)
        if inspect.isawaitable(value):
            value = await value
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    return _fallback


def result_from_artifact(artifact: NarrativeArtifactRecord) -> NarrativeGenerationResult:
    chunks = sentence_chunks(artifact.text) or [artifact.text]
    return NarrativeGenerationResult(
        path_id=artifact.path_id,
        context_version_id=artifact.context_version_id,
        settlement_id=artifact.settlement_id,
        narrative_status=artifact.status,
        text=artifact.text,
        chunks=chunks,
        finding_codes=artifact.finding_codes,
        attempt_count=artifact.attempt_count,
        request_id=artifact.request_id or artifact.artifact_id.hex,
        artifact_id=artifact.artifact_id,
        progress_stages=["context_ready", "generating", "validating", "validated"],
        context_schema_version=artifact.context_schema_version,
        source_versions=artifact.source_versions,
        outcome_stage=artifact.outcome_stage,
        duration_ms=artifact.duration_ms,
    )


async def _buffer_stream(stream: NarrativeStream, context: NarrativeContext) -> str:
    chunks: list[str] = []
    async for chunk in stream(context):
        if chunk:
            chunks.append(str(chunk))
    return "".join(chunks)


async def generate_narrative_artifact(
    *,
    context: NarrativeContext,
    state: GameState,
    generate: NarrativeGenerate,
    stream: NarrativeStream | None = None,
    forbidden_claims: list[str] | None = None,
    provider_label: str | None = None,
    model_label: str | None = None,
    request_id: str | None = None,
    persist: bool = True,
    rule_fallback: NarrativeRuleFallback | None = None,
) -> NarrativeGenerationResult:
    """Generate a safe result without exposing candidate/provider chunks.

    The returned ``chunks`` are derived only after the final candidate passes or
    falls back to committed facts.  Callers may emit them over SSE in order.
    """

    started_at = perf_counter()
    path = get_narrative_path(context.path_id)
    request_id = request_id or uuid4().hex
    fallback = facts_narrative(context)
    attempt_count = 1
    findings: list[NarrativeFinding] = []
    progress_stages: list[
        Literal["context_ready", "generating", "validating", "repairing", "validated"]
    ] = ["context_ready", "generating"]
    generation_failed = False
    try:
        candidate = (
            await _buffer_stream(stream, context)
            if stream is not None
            else await generate(context, None)
        )
    except Exception:
        candidate = ""
        generation_failed = True

    progress_stages.append("validating")
    findings = validate_narrative_candidate(
        candidate,
        context=context,
        state=state,
        forbidden_claims=forbidden_claims,
    )
    if generation_failed:
        findings = [
            NarrativeFinding(
                code="provider_generation_failed",
                message="叙事模型调用失败，未暴露供应商错误内容",
            ),
            *findings,
        ]
    status: Literal["validated", "repaired", "sanitized", "fallback_facts"]
    final_text = candidate.strip()
    if generation_failed:
        configured_fallback = ""
        if rule_fallback is not None:
            try:
                configured_fallback = (await rule_fallback(context) or "").strip()
            except Exception:
                configured_fallback = ""
        if configured_fallback and not validate_narrative_candidate(
            configured_fallback,
            context=context,
            state=state,
            forbidden_claims=forbidden_claims,
        ):
            final_text = configured_fallback
        else:
            final_text = fallback
        status = "fallback_facts"
    elif not findings:
        status = "validated"
    elif path.repair_allowed:
        progress_stages.append("repairing")
        attempt_count = 2
        try:
            repaired = await generate(context, build_repair_instruction(findings))
        except Exception:
            repaired = ""
        repaired_findings = validate_narrative_candidate(
            repaired,
            context=context,
            state=state,
            forbidden_claims=forbidden_claims,
        )
        findings = [*findings, *repaired_findings]
        if not repaired_findings:
            final_text = repaired.strip()
            status = "repaired"
        else:
            final_text, used_fallback = sanitize_candidate(
                repaired,
                repaired_findings,
                fallback=fallback,
            )
            if not used_fallback:
                sanitized_findings = validate_narrative_candidate(
                    final_text,
                    context=context,
                    state=state,
                    forbidden_claims=forbidden_claims,
                )
                findings = [*findings, *sanitized_findings]
                if sanitized_findings:
                    final_text = fallback
                    used_fallback = True
            status = "fallback_facts" if used_fallback else "sanitized"
    else:
        final_text, used_fallback = sanitize_candidate(
            candidate,
            findings,
            fallback=fallback,
        )
        if not used_fallback:
            sanitized_findings = validate_narrative_candidate(
                final_text,
                context=context,
                state=state,
                forbidden_claims=forbidden_claims,
            )
            findings = [*findings, *sanitized_findings]
            if sanitized_findings:
                final_text = fallback
                used_fallback = True
        status = "fallback_facts" if used_fallback else "sanitized"

    if not final_text:
        final_text = fallback
        status = "fallback_facts"
    chunks = sentence_chunks(final_text) or [final_text]
    progress_stages.append("validated")
    finding_codes = sorted({finding.code for finding in findings})
    artifact: NarrativeArtifactRecord | None = None
    duration_ms = max(0, int((perf_counter() - started_at) * 1000))
    source_versions = {
        key: str(value)
        for key, value in context.source_versions.model_dump().items()
        if value is not None
    }
    if persist and context.settlement is not None:
        artifact = save_artifact(
            game_id=context.settlement.game_id,
            branch_id=context.settlement.branch_id,
            settlement_id=context.settlement.settlement_id,
            context_version_id=context.settlement.result_version_id,
            path_id=context.path_id,
            status=status,
            text=final_text,
            finding_codes=finding_codes,
            attempt_count=attempt_count,
            provider_label=provider_label,
            model_label=model_label,
            request_id=request_id,
            context_schema_version=context.schema_version,
            source_versions=source_versions,
            outcome_stage=status,
            duration_ms=duration_ms,
        )
    return NarrativeGenerationResult(
        path_id=context.path_id,
        context_version_id=context.version_id,
        settlement_id=context.settlement_id,
        narrative_status=status,
        text=final_text,
        chunks=chunks,
        finding_codes=finding_codes,
        attempt_count=attempt_count,
        request_id=request_id,
        artifact_id=artifact.artifact_id if artifact is not None else None,
        progress_stages=progress_stages,
        context_schema_version=context.schema_version,
        source_versions=source_versions,
        outcome_stage=status,
        duration_ms=duration_ms,
    )
