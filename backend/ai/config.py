"""Canonical AI settings model shared by settings routes and runtime providers.

The public settings form, draft probes, persisted configuration, and runtime
provider construction must all pass through this module.  Secrets remain in
memory and are never included in public views or logs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit


SECRET_MASK = "********"
EFFECTIVE_PROOF_ENV = "AI_EFFECTIVE_CONFIG_PROOF"
EFFECTIVE_PROOF_VERSION_ENV = "AI_EFFECTIVE_CONFIG_VERSION"
EFFECTIVE_PROOF_VERSION = "1"
INSTALL_SECRET_PATH = Path(__file__).resolve().parents[1] / ".ai_settings_secret"

ThinkingValue = str | bool | int
ThinkingConfig = dict[str, ThinkingValue]


@dataclass(frozen=True, slots=True)
class ProviderEnvSpec:
    api_key_env: str
    base_url_env: str
    model_env: str
    simple_model_env: str
    provider_type_env: str
    enable_thinking_env: str
    enable_thinking_simple_env: str
    thinking_config_env: str
    thinking_config_simple_env: str
    default_base_url: str | None = None
    fixed_provider_type: str | None = None
    legacy_api_key_envs: tuple[str, ...] = ()
    legacy_base_url_envs: tuple[str, ...] = ()
    legacy_model_envs: tuple[str, ...] = ()


PROVIDER_SPECS: dict[str, ProviderEnvSpec] = {
    "openai": ProviderEnvSpec(
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        model_env="OPENAI_MODEL_NAME",
        simple_model_env="OPENAI_SIMPLE_MODEL",
        provider_type_env="OPENAI_PROVIDER_TYPE",
        enable_thinking_env="OPENAI_ENABLE_THINKING",
        enable_thinking_simple_env="OPENAI_ENABLE_THINKING_SIMPLE",
        thinking_config_env="OPENAI_THINKING_CONFIG",
        thinking_config_simple_env="OPENAI_THINKING_CONFIG_SIMPLE",
        default_base_url="https://api.openai.com/v1",
        fixed_provider_type="openai",
    ),
    "google": ProviderEnvSpec(
        api_key_env="GOOGLE_API_KEY",
        base_url_env="GOOGLE_BASE_URL",
        model_env="GOOGLE_MODEL_NAME",
        simple_model_env="GOOGLE_SIMPLE_MODEL",
        provider_type_env="GOOGLE_PROVIDER_TYPE",
        enable_thinking_env="GOOGLE_ENABLE_THINKING",
        enable_thinking_simple_env="GOOGLE_ENABLE_THINKING_SIMPLE",
        thinking_config_env="GOOGLE_THINKING_CONFIG",
        thinking_config_simple_env="GOOGLE_THINKING_CONFIG_SIMPLE",
        default_base_url="https://generativelanguage.googleapis.com",
        fixed_provider_type="google",
    ),
    "h": ProviderEnvSpec(
        api_key_env="HOTARU_API_KEY",
        base_url_env="HOTARU_BASE_URL",
        model_env="HOTARU_MODEL",
        simple_model_env="HOTARU_SIMPLE_MODEL",
        provider_type_env="HOTARU_PROVIDER_TYPE",
        enable_thinking_env="HOTARU_ENABLE_THINKING",
        enable_thinking_simple_env="HOTARU_ENABLE_THINKING_SIMPLE",
        thinking_config_env="HOTARU_THINKING_CONFIG",
        thinking_config_simple_env="HOTARU_THINKING_CONFIG_SIMPLE",
        fixed_provider_type="openai",
        legacy_api_key_envs=("H_API_KEY",),
        legacy_base_url_envs=("H_BASE_URL",),
        legacy_model_envs=("H_MODEL",),
    ),
    "Z": ProviderEnvSpec(
        api_key_env="Z_API_KEY",
        base_url_env="Z_BASE_URL",
        model_env="Z_MODEL",
        simple_model_env="Z_SIMPLE_MODEL",
        provider_type_env="Z_PROVIDER_TYPE",
        enable_thinking_env="Z_ENABLE_THINKING",
        enable_thinking_simple_env="Z_ENABLE_THINKING_SIMPLE",
        thinking_config_env="Z_THINKING_CONFIG",
        thinking_config_simple_env="Z_THINKING_CONFIG_SIMPLE",
        fixed_provider_type="openai",
    ),
}

PROVIDER_ALIASES = {
    "openai": "openai",
    "google": "google",
    "gemini": "google",
    "h": "h",
    "hotaru": "h",
    "z": "Z",
}

SUPPORTED_PROVIDER_TYPES = {
    "openai",
    "openai-response",
    "deepseek",
    "google",
    "anthropic",
}


class AIConfigurationError(ValueError):
    """Stable configuration failure safe to expose through an API mapping."""

    def __init__(self, error_code: str, message: str, *, field_name: str | None = None):
        self.error_code = error_code
        self.message = message
        self.field_name = field_name
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class AIProviderConfig:
    provider: str
    provider_type: str
    api_key: str = field(repr=False)
    base_url: str
    model: str
    simple_model: str | None = None
    enable_thinking: bool = False
    enable_thinking_simple: bool = False
    thinking_config: ThinkingConfig | None = None
    thinking_config_simple: ThinkingConfig | None = None
    sources: Mapping[str, str] = field(default_factory=dict, compare=False, repr=False)

    def canonical_payload(self) -> dict[str, object]:
        """Return the byte-stable private payload used by every fingerprint."""

        return {
            "provider": self.provider,
            "provider_type": self.provider_type,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "simple_model": self.simple_model,
            "enable_thinking": self.enable_thinking,
            "enable_thinking_simple": self.enable_thinking_simple,
            "thinking_config": self.thinking_config,
            "thinking_config_simple": self.thinking_config_simple,
        }

    def canonical_json(self) -> bytes:
        return json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def public_identity(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "provider_type": self.provider_type,
            "base_url": self.base_url,
            "model": self.model,
            "simple_model": self.simple_model,
            "enable_thinking": self.enable_thinking,
            "enable_thinking_simple": self.enable_thinking_simple,
            "thinking_config": self.thinking_config,
            "thinking_config_simple": self.thinking_config_simple,
        }


def clean_optional(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def normalize_provider_name(raw: object, *, default: str | None = None) -> str:
    value = clean_optional(raw) or clean_optional(default)
    if not value:
        raise AIConfigurationError(
            "ai_configuration_required",
            "尚未选择 AI 供应商，请先完成 BYOK 设置。",
            field_name="provider",
        )
    return PROVIDER_ALIASES.get(value.lower(), value)


def provider_spec(provider: str) -> ProviderEnvSpec:
    known = PROVIDER_SPECS.get(provider)
    if known is not None:
        return known
    prefix = provider.upper().replace("-", "_").replace(" ", "_")
    return ProviderEnvSpec(
        api_key_env=f"{prefix}_API_KEY",
        base_url_env=f"{prefix}_BASE_URL",
        model_env=f"{prefix}_MODEL",
        simple_model_env=f"{prefix}_SIMPLE_MODEL",
        provider_type_env=f"{prefix}_PROVIDER_TYPE",
        enable_thinking_env=f"{prefix}_ENABLE_THINKING",
        enable_thinking_simple_env=f"{prefix}_ENABLE_THINKING_SIMPLE",
        thinking_config_env=f"{prefix}_THINKING_CONFIG",
        thinking_config_simple_env=f"{prefix}_THINKING_CONFIG_SIMPLE",
    )


def normalize_provider_type(provider: str, raw: object) -> str:
    spec = provider_spec(provider)
    if spec.fixed_provider_type is not None:
        return spec.fixed_provider_type
    value = (clean_optional(raw) or "openai").lower()
    if value == "gemini":
        value = "google"
    if value not in SUPPORTED_PROVIDER_TYPES:
        raise AIConfigurationError(
            "invalid_provider_type",
            "Provider Type 不受支持，请重新选择。",
            field_name="provider_type",
        )
    return value


def normalize_base_url(raw: object, *, provider: str, provider_type: str) -> str:
    spec = provider_spec(provider)
    base = clean_optional(raw) or spec.default_base_url
    if not base:
        raise AIConfigurationError(
            "invalid_base_url",
            "该供应商必须填写公网 HTTPS Base URL。",
            field_name="base_url",
        )
    base = base.rstrip("/")
    lowered = base.lower()
    if provider_type == "google":
        for suffix in ("/v1beta", "/v1"):
            if lowered.endswith(suffix):
                base = base[: -len(suffix)]
                break
    else:
        for suffix in ("/chat/completions", "/responses"):
            if lowered.endswith(suffix):
                base = base[: -len(suffix)]
                break
    # Round-trip through urllib to normalize a trailing slash without changing
    # the caller-supplied host casing or path semantics.
    parsed = urlsplit(base.rstrip("/"))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), parsed.query, parsed.fragment))


def normalize_thinking_config(raw: object, *, field_name: str) -> ThinkingConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise AIConfigurationError(
            "invalid_ai_settings",
            f"{field_name} 必须是对象。",
            field_name=field_name,
        )
    normalized: ThinkingConfig = {}
    for key in sorted(raw):
        value = raw[key]
        if not isinstance(key, str) or not key.strip():
            raise AIConfigurationError(
                "invalid_ai_settings",
                f"{field_name} 含无效字段名。",
                field_name=field_name,
            )
        if isinstance(value, bool) or isinstance(value, (str, int)):
            normalized[key.strip()] = value
            continue
        raise AIConfigurationError(
            "invalid_ai_settings",
            f"{field_name}.{key} 只允许字符串、整数或布尔值。",
            field_name=field_name,
        )
    return normalized or None


def resolve_submitted_secret(
    submitted: object,
    *,
    current_secret: str | None,
    same_provider: bool,
) -> str | None:
    value = clean_optional(submitted)
    if value == SECRET_MASK:
        if not same_provider or not clean_optional(current_secret):
            raise AIConfigurationError(
                "missing_api_key",
                "当前供应商没有可复用的 API Key，请重新填写。",
                field_name="api_key",
            )
        return clean_optional(current_secret)
    return value


def normalize_ai_config(
    *,
    provider: object,
    provider_type: object = None,
    api_key: object = None,
    base_url: object = None,
    model: object = None,
    simple_model: object = None,
    enable_thinking: object = False,
    enable_thinking_simple: object = False,
    thinking_config: object = None,
    thinking_config_simple: object = None,
    current_provider: str | None = None,
    current_api_key: str | None = None,
    sources: Mapping[str, str] | None = None,
) -> AIProviderConfig:
    normalized_provider = normalize_provider_name(provider)
    normalized_type = normalize_provider_type(normalized_provider, provider_type)
    secret = resolve_submitted_secret(
        api_key,
        current_secret=current_api_key,
        same_provider=current_provider == normalized_provider,
    )
    if not secret:
        raise AIConfigurationError(
            "missing_api_key",
            "API Key 为必填项。",
            field_name="api_key",
        )
    normalized_model = clean_optional(model)
    if not normalized_model:
        raise AIConfigurationError(
            "missing_model",
            "主模型为必填项。",
            field_name="model",
        )
    normalized_base = normalize_base_url(
        base_url,
        provider=normalized_provider,
        provider_type=normalized_type,
    )
    return AIProviderConfig(
        provider=normalized_provider,
        provider_type=normalized_type,
        api_key=secret,
        base_url=normalized_base,
        model=normalized_model,
        simple_model=clean_optional(simple_model),
        enable_thinking=bool(enable_thinking),
        enable_thinking_simple=bool(enable_thinking_simple),
        thinking_config=normalize_thinking_config(thinking_config, field_name="thinking_config"),
        thinking_config_simple=normalize_thinking_config(
            thinking_config_simple,
            field_name="thinking_config_simple",
        ),
        sources=dict(sources or {}),
    )


def _read_first(environment: Mapping[str, str], names: tuple[str, ...]) -> tuple[str | None, str | None]:
    for name in names:
        value = clean_optional(environment.get(name))
        if value is not None:
            return value, name
    return None, None


def _parse_env_bool(environment: Mapping[str, str], name: str) -> bool:
    return (environment.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_env_thinking(environment: Mapping[str, str], name: str) -> ThinkingConfig | None:
    raw = clean_optional(environment.get(name))
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AIConfigurationError(
            "ai_configuration_invalid",
            f"已保存的 {name} 不是有效 JSON，请重新测试并保存。",
            field_name=name,
        ) from exc
    return normalize_thinking_config(value, field_name=name)


def config_from_environment(
    environment: Mapping[str, str] | None = None,
    *,
    provider_name: str | None = None,
) -> AIProviderConfig:
    env = os.environ if environment is None else environment
    provider = normalize_provider_name(provider_name or env.get("AI_PROVIDER"))
    spec = provider_spec(provider)
    api_key, api_key_name = _read_first(env, (spec.api_key_env, *spec.legacy_api_key_envs))
    base_url, base_url_name = _read_first(env, (spec.base_url_env, *spec.legacy_base_url_envs))
    model, model_name = _read_first(env, (spec.model_env, *spec.legacy_model_envs))
    provider_type = env.get(spec.provider_type_env)
    sources = {
        "provider": "saved" if env.get("AI_PROVIDER") else "missing",
        "api_key": "saved" if api_key_name == spec.api_key_env else "legacy_env" if api_key_name else "missing",
        "base_url": "saved" if base_url_name == spec.base_url_env else "legacy_env" if base_url_name else "provider_default" if spec.default_base_url else "missing",
        "model": "saved" if model_name == spec.model_env else "legacy_env" if model_name else "missing",
        "simple_model": "saved" if clean_optional(env.get(spec.simple_model_env)) else "missing",
        "provider_type": "saved" if clean_optional(provider_type) else "provider_default",
    }
    return normalize_ai_config(
        provider=provider,
        provider_type=provider_type,
        api_key=api_key,
        base_url=base_url,
        model=model,
        simple_model=env.get(spec.simple_model_env),
        enable_thinking=_parse_env_bool(env, spec.enable_thinking_env),
        enable_thinking_simple=_parse_env_bool(env, spec.enable_thinking_simple_env),
        thinking_config=_parse_env_thinking(env, spec.thinking_config_env),
        thinking_config_simple=_parse_env_thinking(env, spec.thinking_config_simple_env),
        sources=sources,
    )


def config_hmac(config: AIProviderConfig, secret: bytes, *, domain: bytes) -> str:
    return hmac.new(secret, domain + b"\0" + config.canonical_json(), hashlib.sha256).hexdigest()


def effective_config_proof(config: AIProviderConfig, install_secret: bytes) -> str:
    return config_hmac(config, install_secret, domain=b"ming/ai/effective-config/v1")


def assessment_fingerprint(config: AIProviderConfig, install_secret: bytes) -> str:
    return config_hmac(config, install_secret, domain=b"ming/ai/assessment/v1")


def verification_fingerprint(config: AIProviderConfig, process_secret: bytes) -> str:
    return config_hmac(config, process_secret, domain=b"ming/ai/verification/v1")


def load_or_create_install_secret(path: Path | None = None) -> bytes:
    secret_path = path or INSTALL_SECRET_PATH
    try:
        existing = secret_path.read_bytes()
    except FileNotFoundError:
        existing = b""
    if len(existing) >= 32:
        return existing
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_bytes(32)
    try:
        fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        current = secret_path.read_bytes()
        if len(current) < 32:
            raise AIConfigurationError(
                "ai_configuration_invalid",
                "安装级 AI 配置密钥已损坏，请重新完成设置。",
            )
        return current
    with os.fdopen(fd, "wb") as handle:
        handle.write(generated)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        secret_path.chmod(0o600)
    except OSError:
        pass
    return generated


def load_effective_ai_config(
    environment: Mapping[str, str] | None = None,
    *,
    install_secret: bytes | None = None,
    install_secret_path: Path | None = None,
) -> AIProviderConfig:
    env = os.environ if environment is None else environment
    config = config_from_environment(env)
    proof = clean_optional(env.get(EFFECTIVE_PROOF_ENV))
    version = clean_optional(env.get(EFFECTIVE_PROOF_VERSION_ENV))
    if not proof or version != EFFECTIVE_PROOF_VERSION:
        raise AIConfigurationError(
            "ai_configuration_required",
            "当前 AI 配置尚未经过真实连接测试并应用，请先前往设置。",
        )
    secret = install_secret or load_or_create_install_secret(install_secret_path)
    expected = effective_config_proof(config, secret)
    if not hmac.compare_digest(proof, expected):
        raise AIConfigurationError(
            "ai_configuration_invalid",
            "当前 AI 配置已变化或无法验证，请重新测试并应用。",
        )
    return config


def config_env_updates(config: AIProviderConfig, install_secret: bytes) -> dict[str, str | None]:
    spec = provider_spec(config.provider)
    updates: dict[str, str | None] = {
        "AI_PROVIDER": config.provider,
        spec.api_key_env: config.api_key,
        spec.base_url_env: config.base_url,
        spec.model_env: config.model,
        spec.simple_model_env: config.simple_model,
        spec.provider_type_env: config.provider_type,
        spec.enable_thinking_env: "1" if config.enable_thinking else "0",
        spec.enable_thinking_simple_env: "1" if config.enable_thinking_simple else "0",
        spec.thinking_config_env: (
            json.dumps(config.thinking_config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if config.thinking_config is not None
            else None
        ),
        spec.thinking_config_simple_env: (
            json.dumps(config.thinking_config_simple, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if config.thinking_config_simple is not None
            else None
        ),
        EFFECTIVE_PROOF_ENV: effective_config_proof(config, install_secret),
        EFFECTIVE_PROOF_VERSION_ENV: EFFECTIVE_PROOF_VERSION,
    }
    if config.provider not in PROVIDER_SPECS:
        existing = [
            item.strip()
            for item in (os.getenv("AI_CUSTOM_PROVIDERS") or "").split(",")
            if item.strip()
        ]
        if config.provider not in existing:
            existing.append(config.provider)
        updates["AI_CUSTOM_PROVIDERS"] = ",".join(existing)
    return updates
