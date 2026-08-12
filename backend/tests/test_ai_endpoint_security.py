from __future__ import annotations

import asyncio

import httpx
import pytest

from ai.endpoint_security import (
    PinnedDNSAsyncTransport,
    UnsafeEndpointError,
    create_safe_async_client,
    resolve_public_endpoint,
    validate_base_url_structure,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",
        "https://user:pass@api.example.com/v1",
        "https://localhost/v1",
        "https://127.0.0.1/v1",
        "https://[::1]/v1",
        "https://api.example.com/v1?token=secret",
        "https://api.example.com/v1#fragment",
    ],
)
def test_structure_rejects_non_public_or_ambiguous_base_urls(url):
    with pytest.raises(UnsafeEndpointError):
        validate_base_url_structure(url)


def test_dns_rejects_empty_private_or_mixed_results():
    async def resolve(values):
        async def resolver(_host: str, _port: int):
            return values

        return await resolve_public_endpoint(
            "https://api.example.com/v1",
            resolver=resolver,
        )

    with pytest.raises(UnsafeEndpointError):
        asyncio.run(resolve([]))
    with pytest.raises(UnsafeEndpointError):
        asyncio.run(resolve(["10.0.0.1"]))
    with pytest.raises(UnsafeEndpointError):
        asyncio.run(resolve(["93.184.216.34", "192.168.1.10"]))

    result = asyncio.run(resolve(["93.184.216.34", "2606:4700:4700::1111"]))
    assert result.hostname == "api.example.com"


class _CaptureTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.request: httpx.Request | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.request = request
        return httpx.Response(200, json={"ok": True}, request=request)


def test_transport_pins_ip_but_preserves_host_and_tls_sni():
    capture = _CaptureTransport()

    async def resolver(_host: str, _port: int):
        return ["93.184.216.34"]

    async def run():
        transport = PinnedDNSAsyncTransport(
            allowed_hostname="api.example.com",
            resolver=resolver,
            delegate=capture,
        )
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.get("https://api.example.com/v1/models")
            assert response.status_code == 200

    asyncio.run(run())
    assert capture.request is not None
    assert capture.request.url.host == "93.184.216.34"
    assert capture.request.headers["host"] == "api.example.com"
    assert capture.request.extensions["sni_hostname"] == "api.example.com"


def test_transport_rejects_cross_host_requests():
    async def resolver(_host: str, _port: int):
        return ["93.184.216.34"]

    async def run():
        transport = PinnedDNSAsyncTransport(
            allowed_hostname="api.example.com",
            resolver=resolver,
            delegate=_CaptureTransport(),
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(UnsafeEndpointError):
                await client.get("https://other.example.com/v1")

    asyncio.run(run())


def test_explicit_operator_proxy_owns_dns_resolution(monkeypatch):
    monkeypatch.setenv("AI_USE_SYSTEM_PROXY", "1")
    monkeypatch.setenv("AI_PROXY_ALLOWED_HOSTS", "api.deepseek.com")
    monkeypatch.setenv("AI_PROXY_URL", "http://127.0.0.1:7897")

    async def resolver(_host: str, _port: int):
        raise AssertionError("proxy mode must not perform local DNS resolution")

    endpoint = asyncio.run(
        resolve_public_endpoint(
            "https://api.deepseek.com",
            resolver=resolver,
        ),
    )
    assert endpoint.proxy_url == "http://127.0.0.1:7897"
    assert endpoint.addresses == ("api.deepseek.com",)

    client = create_safe_async_client("https://api.deepseek.com")
    try:
        assert client._trust_env is False
        assert not isinstance(client._transport, PinnedDNSAsyncTransport)
    finally:
        asyncio.run(client.aclose())


def test_operator_proxy_requires_target_allowlist(monkeypatch):
    monkeypatch.setenv("AI_USE_SYSTEM_PROXY", "1")
    monkeypatch.delenv("AI_PROXY_ALLOWED_HOSTS", raising=False)
    monkeypatch.setenv("AI_PROXY_URL", "http://127.0.0.1:7897")
    with pytest.raises(UnsafeEndpointError, match="AI_PROXY_ALLOWED_HOSTS"):
        asyncio.run(resolve_public_endpoint("https://api.deepseek.com"))


def test_operator_proxy_rejects_missing_proxy_url(monkeypatch):
    monkeypatch.setenv("AI_USE_SYSTEM_PROXY", "1")
    monkeypatch.setenv("AI_PROXY_ALLOWED_HOSTS", "api.deepseek.com")
    monkeypatch.delenv("AI_PROXY_URL", raising=False)
    with pytest.raises(UnsafeEndpointError, match="AI_PROXY_URL"):
        asyncio.run(resolve_public_endpoint("https://api.deepseek.com"))
