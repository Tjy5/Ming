"""08-07-improve-ai-settings-page 后端测试：错误分类映射。

验证 ai.errors._map_provider_error 对各类异常的 error_code 映射正确，
供前端诊断展示。
"""

import json
import logging

import httpx
import openai
import pytest

from ai.errors import (
    ERROR_DIAGNOSIS,
    _map_provider_error,
    log_safe_provider_exception,
    public_error_detail,
)


def _resp(status: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status, request=httpx.Request("GET", "http://x"))


def _openai_exc(cls, status: int = 400):
    return cls(message="e", response=_resp(status), body=None)


class TestMapProviderError:
    def test_auth_error(self):
        assert _map_provider_error(_openai_exc(openai.AuthenticationError, 401))["error_code"] == "invalid_api_key"

    def test_permission_denied_is_a_stable_auth_error(self):
        mapped = _map_provider_error(_openai_exc(openai.PermissionDeniedError, 403))
        assert mapped["error_code"] == "invalid_api_key"
        assert mapped["message"] == ERROR_DIAGNOSIS["invalid_api_key"].message
        assert mapped["fix_hint"] == ERROR_DIAGNOSIS["invalid_api_key"].fix_hint

    def test_rate_limit(self):
        assert _map_provider_error(_openai_exc(openai.RateLimitError, 429))["error_code"] == "quota"

    def test_not_found(self):
        assert _map_provider_error(_openai_exc(openai.NotFoundError, 404))["error_code"] == "model_not_found"

    def test_status_error(self):
        assert _map_provider_error(_openai_exc(openai.APIStatusError, 500))["error_code"] == "provider_unavailable"

    def test_timeout(self):
        exc = openai.APITimeoutError(request=httpx.Request("GET", "http://x"))
        assert _map_provider_error(exc)["error_code"] == "timeout"

    def test_connection(self):
        exc = openai.APIConnectionError(request=httpx.Request("GET", "http://x"))
        assert _map_provider_error(exc)["error_code"] == "network"

    def test_httpx_connect(self):
        exc = httpx.ConnectError("conn")
        assert _map_provider_error(exc)["error_code"] == "network"

    def test_httpx_unsupported_protocol(self):
        exc = httpx.UnsupportedProtocol("ftp://x")
        assert _map_provider_error(exc)["error_code"] == "invalid_base_url"

    def test_json_decode(self):
        exc = json.JSONDecodeError("e", "doc", 0)
        assert _map_provider_error(exc)["error_code"] == "invalid_response"

    def test_fallback(self):
        exc = RuntimeError("weird")
        assert _map_provider_error(exc)["error_code"] == "provider_unavailable"

    def test_diagnosis_covers_all_codes(self):
        # 所有映射出的 error_code 都应有前端可读诊断
        samples = [
            _openai_exc(openai.AuthenticationError, 401),
            _openai_exc(openai.RateLimitError, 429),
            _openai_exc(openai.NotFoundError, 404),
            _openai_exc(openai.APIStatusError, 500),
            openai.APITimeoutError(request=httpx.Request("GET", "http://x")),
            openai.APIConnectionError(request=httpx.Request("GET", "http://x")),
            httpx.UnsupportedProtocol("ftp://x"),
            json.JSONDecodeError("e", "d", 0),
            RuntimeError("x"),
        ]
        for s in samples:
            code = _map_provider_error(s)["error_code"]
            assert code in ERROR_DIAGNOSIS, f"{code} 缺少前端诊断文案"

    def test_public_mapping_never_leaks_exception_or_response_body(self):
        canary = "sk-super-secret Authorization: Bearer leak-me"
        request = httpx.Request("POST", "https://api.example.com/v1")
        response = httpx.Response(500, text=canary, request=request)
        mapped = _map_provider_error(
            httpx.HTTPStatusError(canary, request=request, response=response),
        )
        serialized = json.dumps(mapped, ensure_ascii=False)
        assert canary not in serialized
        assert "leak-me" not in serialized
        assert "HTTP 500" in (mapped["provider_summary"] or "")

    def test_public_error_contains_stable_fix_fields(self):
        detail = public_error_detail("invalid_api_key", request_id="ai_test")
        assert detail["request_id"] == "ai_test"
        assert detail["fix_hint"]
        assert detail["retryable"] is False

    def test_safe_provider_log_never_formats_exception_text(self, caplog):
        canary = "sk-log-secret Authorization: Bearer log-leak"
        logger = logging.getLogger("test.ai.safe-log")

        with caplog.at_level(logging.ERROR, logger=logger.name):
            log_safe_provider_exception(
                logger,
                stage="probe_generation_once",
                exc=RuntimeError(canary),
            )

        assert "probe_generation_once" in caplog.text
        assert "RuntimeError" in caplog.text
        assert canary not in caplog.text
        assert "log-leak" not in caplog.text
