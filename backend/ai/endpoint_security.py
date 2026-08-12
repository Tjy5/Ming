"""Fail-closed public HTTPS policy for all settings-managed AI traffic."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


Resolver = Callable[[str, int], Awaitable[Iterable[str]]]


class UnsafeEndpointError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedEndpoint:
    base_url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]
    proxy_url: str | None = None


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _proxy_host_allowed(hostname: str) -> bool:
    """Return whether an operator-approved proxy may receive this hostname.

    Proxy mode intentionally requires an explicit allowlist.  This keeps a
    local Clash proxy from becoming a generic SSRF bypass for player-supplied
    Base URLs while still allowing Clash to resolve and route approved public
    providers.
    """

    raw = os.environ.get("AI_PROXY_ALLOWED_HOSTS", "")
    allowed = {item.strip().rstrip(".").lower() for item in raw.split(",") if item.strip()}
    return hostname in allowed or any(
        item.startswith("*.") and hostname.endswith(item[1:])
        for item in allowed
    )


def _operator_proxy_url(base_url: str, *, provider: str) -> str | None:
    """Read the explicit operator proxy used for Clash-routed AI traffic.

    The normal product path remains direct and fail-closed.  Proxy mode is an
    operator-only switch: it must be enabled explicitly, name an approved
    target host, and provide a concrete HTTP(S) proxy URL.  The proxy handles
    DNS, so the local resolver is not consulted in this mode.
    """

    if not (_env_flag("AI_USE_SYSTEM_PROXY") or _env_flag("OPENAI_TRUST_ENV_PROXY")):
        return None
    hostname = (urlsplit(base_url).hostname or "").rstrip(".").lower()
    if not _proxy_host_allowed(hostname):
        raise UnsafeEndpointError(
            f"{provider} Base URL 未在 AI_PROXY_ALLOWED_HOSTS 中，不能通过系统代理访问。",
        )
    proxy_url = (os.environ.get("AI_PROXY_URL") or "").strip()
    if not proxy_url:
        raise UnsafeEndpointError(
            f"{provider} 已启用系统代理，但未配置 AI_PROXY_URL。",
        )
    try:
        parsed = urlsplit(proxy_url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeEndpointError("AI_PROXY_URL 端口或格式无效。") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise UnsafeEndpointError("AI_PROXY_URL 只允许 HTTP 或 HTTPS 代理。")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeEndpointError("AI_PROXY_URL 不允许内嵌代理账号信息。")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise UnsafeEndpointError("AI_PROXY_URL 不允许 path、query 或 fragment。")
    if port is not None and not 1 <= port <= 65535:
        raise UnsafeEndpointError("AI_PROXY_URL 端口无效。")
    return proxy_url.rstrip("/")


def _normalized_ip(raw: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    value = raw.split("%", 1)[0].strip()
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def is_public_address(raw: str) -> bool:
    try:
        address = _normalized_ip(raw)
    except ValueError:
        return False
    return address.is_global


def validate_base_url_structure(base_url: str, *, provider: str = "AI") -> str:
    value = (base_url or "").strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeEndpointError(f"{provider} Base URL 端口或格式无效。") from exc
    if parsed.scheme.lower() != "https":
        raise UnsafeEndpointError(f"{provider} Base URL 只允许公网 HTTPS。")
    if not parsed.hostname:
        raise UnsafeEndpointError(f"{provider} Base URL 缺少主机名。")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeEndpointError(f"{provider} Base URL 不允许内嵌账号信息。")
    if parsed.query or parsed.fragment:
        raise UnsafeEndpointError(f"{provider} Base URL 不允许 query 或 fragment。")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeEndpointError(f"{provider} Base URL 不允许 localhost。")
    if "%" in parsed.hostname:
        raise UnsafeEndpointError(f"{provider} Base URL 不允许 IP zone identifier。")
    try:
        literal = _normalized_ip(host)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise UnsafeEndpointError(f"{provider} Base URL 必须指向公网地址。")
    if port is not None and not 1 <= port <= 65535:
        raise UnsafeEndpointError(f"{provider} Base URL 端口无效。")
    return value.rstrip("/")


async def default_resolver(hostname: str, port: int) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(
        hostname,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    return tuple(dict.fromkeys(str(info[4][0]) for info in infos))


async def resolve_public_endpoint(
    base_url: str,
    *,
    provider: str = "AI",
    resolver: Resolver | None = None,
) -> ResolvedEndpoint:
    validated = validate_base_url_structure(base_url, provider=provider)
    parsed = urlsplit(validated)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    port = parsed.port or 443
    proxy_url = _operator_proxy_url(validated, provider=provider)
    if proxy_url is not None:
        # The explicit proxy owns DNS resolution.  Keep a non-empty marker in
        # the endpoint for callers that only need a validated identity; the
        # proxy client never passes this marker to a direct transport.
        return ResolvedEndpoint(
            base_url=validated,
            hostname=hostname,
            port=port,
            addresses=(hostname,),
            proxy_url=proxy_url,
        )
    try:
        literal = _normalized_ip(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = (str(literal),)
    else:
        try:
            resolved = await (resolver or default_resolver)(hostname, port)
        except (OSError, socket.gaierror) as exc:
            raise UnsafeEndpointError(f"{provider} Base URL 无法解析 DNS。") from exc
        addresses = tuple(dict.fromkeys(str(item).strip() for item in resolved if str(item).strip()))
    if not addresses:
        raise UnsafeEndpointError(f"{provider} Base URL 没有可用 DNS 结果。")
    if any(not is_public_address(item) for item in addresses):
        raise UnsafeEndpointError(f"{provider} Base URL 的 DNS 结果包含非公网地址。")
    return ResolvedEndpoint(
        base_url=validated,
        hostname=hostname,
        port=port,
        addresses=addresses,
    )


class PinnedDNSAsyncTransport(httpx.AsyncBaseTransport):
    """Resolve, validate, and pin each outbound request to a public address.

    The rewritten connection target prevents a second DNS lookup.  The
    original hostname remains in both the Host header and ``sni_hostname`` so
    TLS certificate verification still authenticates the configured endpoint.
    """

    def __init__(
        self,
        *,
        allowed_hostname: str,
        resolver: Resolver | None = None,
        delegate: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._allowed_hostname = allowed_hostname.rstrip(".").lower()
        self._resolver = resolver
        self._delegate = delegate or httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        original_host = (request.url.host or "").rstrip(".").lower()
        if original_host != self._allowed_hostname:
            raise UnsafeEndpointError("AI 请求试图离开已验证的供应商主机。")
        endpoint = await resolve_public_endpoint(
            str(request.url.copy_with(path="/", query=None, fragment=None)),
            resolver=self._resolver,
        )
        if endpoint.proxy_url is not None:
            raise UnsafeEndpointError(
                "AI 系统代理必须使用显式代理客户端，不能回落到直连 transport。",
            )
        pinned_url = request.url.copy_with(host=endpoint.addresses[0])
        headers = request.headers.copy()
        default_port = request.url.port in {None, 443}
        headers["Host"] = original_host if default_port else f"{original_host}:{request.url.port}"
        extensions = dict(request.extensions)
        extensions["sni_hostname"] = original_host
        pinned_request = httpx.Request(
            method=request.method,
            url=pinned_url,
            headers=headers,
            stream=request.stream,
            extensions=extensions,
        )
        return await self._delegate.handle_async_request(pinned_request)

    async def aclose(self) -> None:
        await self._delegate.aclose()


def create_safe_async_client(
    base_url: str,
    *,
    resolver: Resolver | None = None,
    timeout: float = 30.0,
) -> httpx.AsyncClient:
    validated = validate_base_url_structure(base_url)
    hostname = (urlsplit(validated).hostname or "").rstrip(".").lower()
    proxy_url = _operator_proxy_url(validated, provider="AI")
    if proxy_url is not None:
        return httpx.AsyncClient(
            proxy=proxy_url,
            timeout=timeout,
            # Do not consult HTTP(S)_PROXY/NO_PROXY after the explicit proxy
            # was selected.  This prevents accidental direct fallback.
            trust_env=False,
            follow_redirects=False,
        )
    return httpx.AsyncClient(
        transport=PinnedDNSAsyncTransport(
            allowed_hostname=hostname,
            resolver=resolver,
        ),
        timeout=timeout,
        trust_env=False,
        follow_redirects=False,
    )
