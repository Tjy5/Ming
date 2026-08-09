"""Optional four-scenario capability assessment with deterministic validators."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .base import AIProvider, GenerationResult
from .parsers import extract_json_object_text


VALIDATOR_VERSION = "ai-settings-capability-v1"


@dataclass(frozen=True, slots=True)
class AssessmentScenario:
    key: str
    prompt: str
    validator: Callable[[object], tuple[str, str]]


def _object(text: str) -> object:
    return json.loads(extract_json_object_text(text))


def _validate_structured(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "fail", "未返回所需 JSON 对象。"
    if payload.get("version") != 1 or payload.get("outcome") not in {"success", "partial", "failure"}:
        return "fail", "版本或结果枚举不符合结构化契约。"
    changes = payload.get("changes")
    if not isinstance(changes, list) or not changes:
        return "fail", "缺少类型化 changes。"
    valid = all(
        isinstance(item, dict)
        and set(item) == {"field", "delta"}
        and item.get("field") in {"grain", "treasury"}
        and isinstance(item.get("delta"), int)
        and not isinstance(item.get("delta"), bool)
        for item in changes
    )
    return ("pass", "能遵从最小结构化输出契约。") if valid else (
        "fail",
        "changes 含未知字段、字段名或非整数增量。",
    )


def _validate_grounding(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "fail", "未返回状态依据对象。"
    actors = payload.get("actors_used")
    changes = payload.get("changed_fields")
    if not isinstance(actors, list) or not set(map(str, actors)).issubset({"林校尉"}):
        return "fail", "引用了未提供或已死亡的主体。"
    if payload.get("dead_actor_active") is not False:
        return "fail", "没有正确区分死亡与存活主体。"
    if not isinstance(changes, list) or not set(map(str, changes)).issubset({"grain"}):
        return "fail", "尝试修改场景未允许的状态字段。"
    return "pass", "能依据给定主体与字段边界作答。"


def _validate_causal(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "fail", "未返回开放行动因果对象。"
    if payload.get("success_degree") not in {"full", "partial", "failed"}:
        return "fail", "缺少有效成功度。"
    required_lists = (
        "key_factors",
        "immediate_consequences",
        "long_term_risks",
        "new_opportunities",
    )
    if any(not isinstance(payload.get(key), list) or not payload[key] for key in required_lists):
        return "fail", "关键因子、后果、风险或机会不完整。"
    return "pass", "能给出开放行动的多层因果裁决。"


def _validate_memory(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "fail", "未返回短期记忆对象。"
    if payload.get("remembered_fact") != "青瓷印信藏在西库第三格":
        return "fail", "未保持短上下文中的分支事实。"
    if payload.get("default_history_used") is not False:
        return "fail", "回答回到了与分支冲突的默认历史。"
    return "pass", "能保持短上下文中的分支事实。"


SCENARIOS: tuple[AssessmentScenario, ...] = (
    AssessmentScenario(
        "structured_schema",
        """只输出 JSON：version 必须为 1；outcome 为 success/partial/failure；changes 是至少一项的数组，每项只能含 field 和整数 delta，field 只能是 grain 或 treasury。模拟粮草增加 2。""",
        _validate_structured,
    ),
    AssessmentScenario(
        "state_grounding",
        """只输出 JSON，字段为 actors_used、dead_actor_active、changed_fields。已知：林校尉存活；周参军已死亡；本次只允许修改 grain。请裁决由林校尉清点粮仓的行动，不得引用其他主体。""",
        _validate_grounding,
    ),
    AssessmentScenario(
        "causal_adjudication",
        """玩家放弃预设路线，决定借春汛秘密开辟商道。只输出 JSON：success_degree(full/partial/failed)、key_factors、immediate_consequences、long_term_risks、new_opportunities，四个数组都至少一项。不要比较任何历史正史答案。""",
        _validate_causal,
    ),
    AssessmentScenario(
        "short_memory",
        """对话事实一：印信原本在东库。分支行动：印信已经移走。分支事实：青瓷印信藏在西库第三格。闲谈一：今日有雨。闲谈二：守门人换班。只输出 JSON：remembered_fact 和 default_history_used，回答当前印信位置。""",
        _validate_memory,
    ),
)


def _safe_validate(scenario: AssessmentScenario, text: str) -> tuple[str, str]:
    try:
        payload = _object(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        return "fail", "返回内容不是可验证的 JSON。"
    return scenario.validator(payload)


async def run_capability_assessment(provider: AIProvider) -> dict[str, Any]:
    results: list[dict[str, str]] = []
    calls_completed = 0
    input_tokens = 0
    output_tokens = 0
    usage_available = True
    stopped_by_transport = False

    for index, scenario in enumerate(SCENARIOS):
        try:
            generated: GenerationResult = await provider.generate_text_once(
                scenario.prompt,
                system_prompt="你是模型能力合同测试器。严格按用户指定的 JSON 契约作答。",
                max_output_tokens=320,
                response_json=True,
            )
            calls_completed += 1
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            # asyncio.CancelledError inherits BaseException on supported Python
            # versions and must propagate so no later scenario starts.
            import asyncio

            if isinstance(exc, asyncio.CancelledError):
                raise
            calls_completed += 1
            results.append(
                {
                    "scenario": scenario.key,
                    "status": "fail",
                    "explanation": "供应商调用失败，评估已停止且不会自动重试。",
                },
            )
            stopped_by_transport = True
            for remaining in SCENARIOS[index + 1 :]:
                results.append(
                    {
                        "scenario": remaining.key,
                        "status": "fail",
                        "explanation": "前序供应商调用失败，本项未发起。",
                    },
                )
            break

        status, explanation = _safe_validate(scenario, generated.text)
        results.append(
            {
                "scenario": scenario.key,
                "status": status,
                "explanation": explanation,
            },
        )
        if generated.input_tokens is None or generated.output_tokens is None:
            usage_available = False
        else:
            input_tokens += generated.input_tokens
            output_tokens += generated.output_tokens

    statuses = [item["status"] for item in results]
    if statuses and all(status == "pass" for status in statuses):
        tier = "excellent"
    elif statuses and all(status in {"pass", "warn"} for status in statuses):
        tier = "usable"
    else:
        tier = "high_risk"
    return {
        "tier": tier,
        "results": results,
        "calls_completed": calls_completed,
        "usage": (
            {"input_tokens": input_tokens, "output_tokens": output_tokens}
            if usage_available
            else None
        ),
        "assessed_at": datetime.now(timezone.utc).isoformat(),
        "validator_version": VALIDATOR_VERSION,
        "stopped_by_transport": stopped_by_transport,
    }
