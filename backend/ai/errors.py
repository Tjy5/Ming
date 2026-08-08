"""AI provider 错误分类映射（08-07-improve-ai-settings-page）。

将底层 SDK / 网络异常映射到稳定 error_code，供前端展示可读诊断。
复用自 settings_routes.py 原有散落 error_code（missing_api_key / invalid_base_url /
model_list_failed），新增 auth/quota/model/network/timeout/format 细分。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import openai

# error_code → 前端诊断文案
ERROR_DIAGNOSIS: dict[str, str] = {
    "missing_api_key": "未填写 API Key，请先在设置中填入。",
    "invalid_api_key": "API Key 无效（401），请核对是否已复制完整、未含多余空格。",
    "quota": "账户额度不足或被限流（429），请检查账单或稍后重试。",
    "model_not_found": "模型名不存在（404），请检查 Model 字段是否拼写正确。",
    "invalid_base_url": "Base URL 格式无效，应为 http(s):// 开头的兼容端点。",
    "network": "网络连接失败，请检查网络、代理或 Base URL 是否可达。",
    "timeout": "请求超时，供应商响应过慢或网络不稳定，请重试。",
    "format": "供应商返回格式异常，请确认 Base URL 指向的是 OpenAI 兼容接口。",
    "model_list_failed": "获取模型列表失败，请检查密钥/地址/网络。",
}


def _map_provider_error(exc: Exception) -> dict[str, Any]:
    """将异常映射为 ErrorResponse 兼容字段。

    返回 {error_code, message}；message 含原始异常摘要便于后端日志，前端用
    ERROR_DIAGNOSIS[error_code] 展示可读原因。
    """
    # 显式 SDK 错误
    if isinstance(exc, openai.AuthenticationError):
        return {"error_code": "invalid_api_key", "message": f"认证失败: {exc}"}
    if isinstance(exc, openai.RateLimitError):
        return {"error_code": "quota", "message": f"限流/额度: {exc}"}
    if isinstance(exc, openai.NotFoundError):
        return {"error_code": "model_not_found", "message": f"资源不存在: {exc}"}
    if isinstance(exc, openai.APITimeoutError):
        return {"error_code": "timeout", "message": f"超时: {exc}"}
    if isinstance(exc, openai.APIConnectionError):
        return {"error_code": "network", "message": f"连接错误: {exc}"}
    if isinstance(exc, openai.APIStatusError):
        return {"error_code": "model_list_failed", "message": f"供应商错误 {exc.status_code}: {exc}"}
    # httpx 层（裸客户端/兼容端点）
    if isinstance(exc, httpx.UnsupportedProtocol):
        return {"error_code": "invalid_base_url", "message": f"协议不支持: {exc}"}
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError)):
        return {"error_code": "network", "message": f"网络错误: {exc}"}
    if isinstance(exc, httpx.TimeoutException):
        return {"error_code": "timeout", "message": f"超时: {exc}"}
    if isinstance(exc, httpx.HTTPStatusError):
        return {"error_code": "model_list_failed", "message": f"HTTP 错误: {exc}"}
    # JSON 解析（兼容端点返回非 JSON）
    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return {"error_code": "format", "message": f"响应解析失败: {exc}"}
    # 兜底
    return {"error_code": "model_list_failed", "message": f"未知错误: {exc}"}
