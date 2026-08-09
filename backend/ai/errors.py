"""Safe AI failure classification and public diagnostic serialization."""

from __future__ import annotations

import json
import logging
import re
import secrets
from dataclasses import dataclass
from typing import Any

import httpx
import openai

from .config import AIConfigurationError
from .endpoint_security import UnsafeEndpointError


@dataclass(frozen=True, slots=True)
class Diagnostic:
    message: str
    fix_hint: str
    retryable: bool = False


ERROR_DIAGNOSIS: dict[str, Diagnostic] = {
    "missing_api_key": Diagnostic(
        "未填写 API Key，当前草稿无法验证。",
        "填写供应商签发的 API Key 后重新测试。",
    ),
    "missing_model": Diagnostic(
        "未填写主模型，当前草稿无法验证。",
        "从供应商模型列表选择或填写一个可用主模型。",
    ),
    "invalid_api_key": Diagnostic(
        "认证失败，当前 API Key 无法使用。",
        "重新复制 API Key，确认没有空格并检查供应商账号状态。",
    ),
    "quota": Diagnostic(
        "供应商拒绝了请求，可能是额度不足或限流。",
        "检查账单与额度；若只是限流，请稍后手动重试。",
        True,
    ),
    "model_not_found": Diagnostic(
        "供应商找不到当前主模型。",
        "核对模型名、账号权限以及 Base URL 所属供应商。",
    ),
    "invalid_provider_type": Diagnostic(
        "Provider Type 不受支持。",
        "重新选择与供应商协议匹配的 Provider Type。",
    ),
    "invalid_base_url": Diagnostic(
        "Base URL 无效或不满足公网 HTTPS 安全要求。",
        "使用不含账号、query、fragment 的公网 HTTPS Base URL。",
    ),
    "unsafe_base_url": Diagnostic(
        "Base URL 或其 DNS 结果指向了非公网地址。",
        "改用供应商公开的 HTTPS API 地址；本产品不支持本地或私网端点。",
    ),
    "network": Diagnostic(
        "无法连接到供应商。",
        "检查网络与 Base URL；确认供应商服务可从当前设备访问。",
        True,
    ),
    "timeout": Diagnostic(
        "供应商在限定时间内没有完成响应。",
        "稍后手动重试，或检查供应商状态与模型响应速度。",
        True,
    ),
    "invalid_response": Diagnostic(
        "供应商返回了无法用于游戏的响应。",
        "确认模型支持当前协议，并核对 Provider Type、模型与 Base URL。",
    ),
    "format": Diagnostic(
        "供应商返回格式异常。",
        "确认 Provider Type 与 Base URL 协议匹配后重新测试。",
    ),
    "provider_unavailable": Diagnostic(
        "供应商服务暂时不可用。",
        "查看供应商状态页，恢复后再手动测试。",
        True,
    ),
    "model_list_failed": Diagnostic(
        "获取模型列表失败。",
        "模型列表仅供辅助；检查地址、密钥和网络后重试。",
        True,
    ),
    "ai_test_required": Diagnostic(
        "当前草稿尚未通过真实生成测试。",
        "先点击“测试连接”，成功后再保存并应用。",
    ),
    "ai_test_expired": Diagnostic(
        "草稿验证已过期。",
        "重新测试当前草稿后再保存。",
    ),
    "ai_test_mismatch": Diagnostic(
        "当前草稿与已验证参数不一致。",
        "字段变化后需要重新测试，再保存并应用。",
    ),
    "ai_test_used": Diagnostic(
        "这份草稿验证已经使用过。",
        "重新测试以取得新的短期验证。",
    ),
    "ai_settings_conflict": Diagnostic(
        "AI 配置文件在保存期间被其他操作修改。",
        "重新加载设置，确认内容后再次测试并保存。",
        True,
    ),
    "ai_settings_apply_failed": Diagnostic(
        "保存并应用失败，原有配置仍保持不变。",
        "根据请求编号查看日志，修复后重新保存。",
        True,
    ),
    "ai_settings_rollback_failed": Diagnostic(
        "保存失败，且至少一项自动恢复操作未能完成。",
        "停止继续操作，并根据请求编号检查服务日志与当前生效配置。",
    ),
    "ai_configuration_required": Diagnostic(
        "尚无已验证并生效的 BYOK AI 配置。",
        "前往 AI 设置填写、测试并保存供应商配置。",
    ),
    "ai_configuration_invalid": Diagnostic(
        "已保存的 AI 配置已失效或无法验证。",
        "重新填写当前配置，完成真实测试后保存并应用。",
    ),
    "invalid_ai_settings": Diagnostic(
        "AI 配置字段无效。",
        "修正标出的字段后重新测试。",
    ),
}


def new_request_id() -> str:
    return f"ai_{secrets.token_hex(8)}"


def log_safe_provider_exception(
    logger: logging.Logger,
    *,
    stage: str,
    exc: BaseException,
    level: int = logging.ERROR,
) -> None:
    """Log only a fixed operation name and exception class, never exception text."""

    logger.log(
        level,
        "AI provider operation failed: stage=%s exception_type=%s",
        stage,
        type(exc).__name__,
    )


@dataclass(slots=True)
class ProviderFailure(Exception):
    error_code: str
    request_id: str
    provider_summary: str | None = None
    status_code: int | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.error_code)

    def public_detail(self) -> dict[str, Any]:
        return public_error_detail(
            self.error_code,
            request_id=self.request_id,
            provider_summary=self.provider_summary,
        )


def public_error_detail(
    error_code: str,
    *,
    request_id: str | None = None,
    provider_summary: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostic = ERROR_DIAGNOSIS.get(error_code, ERROR_DIAGNOSIS["provider_unavailable"])
    payload: dict[str, Any] = {
        "error_code": error_code,
        "message": diagnostic.message,
        "fix_hint": diagnostic.fix_hint,
        "request_id": request_id,
        "provider_summary": provider_summary,
        "retryable": diagnostic.retryable,
        "details": details,
    }
    return payload


def _status_from_exception(exc: Exception) -> int | None:
    if isinstance(exc, openai.APIStatusError):
        return int(exc.status_code)
    if isinstance(exc, httpx.HTTPStatusError):
        return int(exc.response.status_code)
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return int(status) if isinstance(status, int) else None


def _provider_request_id(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    for key in ("x-request-id", "request-id", "x-amzn-requestid", "cf-ray"):
        value = headers.get(key)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,96}", value):
            return value
    return None


def _summary(exc: Exception, *, status: int | None = None) -> str | None:
    parts: list[str] = []
    if status is not None:
        parts.append(f"HTTP {status}")
    known_type = type(exc).__name__
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", known_type):
        parts.append(known_type)
    upstream_id = _provider_request_id(exc)
    if upstream_id:
        parts.append(f"provider request {upstream_id}")
    return " · ".join(parts) or None


def error_code_for_status(status: int) -> str:
    if status in {401, 403}:
        return "invalid_api_key"
    if status == 404:
        return "model_not_found"
    if status == 429:
        return "quota"
    if status in {408, 504}:
        return "timeout"
    if 500 <= status <= 599:
        return "provider_unavailable"
    return "invalid_response"


def _map_provider_error(exc: Exception) -> dict[str, Any]:
    """Compatibility mapping that never includes ``str(exc)`` or response bodies."""

    if isinstance(exc, ProviderFailure):
        return exc.public_detail()
    if isinstance(exc, AIConfigurationError):
        return public_error_detail(exc.error_code)
    if isinstance(exc, UnsafeEndpointError):
        return public_error_detail("unsafe_base_url")
    if isinstance(exc, openai.AuthenticationError):
        code = "invalid_api_key"
    elif isinstance(exc, openai.RateLimitError):
        code = "quota"
    elif isinstance(exc, openai.NotFoundError):
        code = "model_not_found"
    elif isinstance(exc, (openai.APITimeoutError, httpx.TimeoutException)):
        code = "timeout"
    elif isinstance(exc, openai.APIConnectionError):
        code = "network"
    elif isinstance(exc, httpx.UnsupportedProtocol):
        code = "invalid_base_url"
    elif isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        code = "network"
    elif isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        code = "invalid_response"
    else:
        status = _status_from_exception(exc)
        code = error_code_for_status(status) if status is not None else "provider_unavailable"
        detail = public_error_detail(code, provider_summary=_summary(exc, status=status))
        # Keep the old key shape used by a few callers/tests.
        return detail
    status = _status_from_exception(exc)
    return public_error_detail(code, provider_summary=_summary(exc, status=status))


def provider_failure_from_exception(
    exc: Exception,
    *,
    request_id: str,
) -> ProviderFailure:
    mapped = _map_provider_error(exc)
    return ProviderFailure(
        error_code=str(mapped["error_code"]),
        request_id=request_id,
        provider_summary=mapped.get("provider_summary"),
        status_code=_status_from_exception(exc),
    )
