"""Transactional AI settings application, probes, and capability assessment."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
import tempfile
import time
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import set_key, unset_key

from ai.assessment import VALIDATOR_VERSION, run_capability_assessment
from ai.base import AIProvider
from ai.config import (
    AIConfigurationError,
    AIProviderConfig,
    EFFECTIVE_PROOF_ENV,
    EFFECTIVE_PROOF_VERSION_ENV,
    PROVIDER_SPECS,
    SECRET_MASK,
    assessment_fingerprint,
    clean_optional,
    config_env_updates,
    config_from_environment,
    load_effective_ai_config,
    load_or_create_install_secret,
    normalize_ai_config,
    normalize_provider_name,
    normalize_provider_type,
    provider_spec,
    verification_fingerprint,
)
from ai.endpoint_security import (
    Resolver,
    UnsafeEndpointError,
    create_safe_async_client,
    resolve_public_endpoint,
)
from ai.errors import (
    ProviderFailure,
    new_request_id,
    provider_failure_from_exception,
)
from ai.factory import RUNTIME, SINGLE_ATTEMPT, AttemptPolicy, build_provider
from db.ai_assessments import load_assessment, save_assessment


DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
VERIFICATION_TTL_SECONDS = 5 * 60
VERIFICATION_CAPACITY = 256
RUNTIME_RETIRE_GRACE_SECONDS = 130.0


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Grant:
    token_hash: str
    fingerprint: str
    issued_at: float
    expires_at: float
    expires_at_iso: str
    state: str = "issued"


class VerificationStore:
    def __init__(
        self,
        *,
        process_secret: bytes | None = None,
        ttl_seconds: float = VERIFICATION_TTL_SECONDS,
        capacity: int = VERIFICATION_CAPACITY,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._secret = process_secret or secrets.token_bytes(32)
        self._ttl = max(1.0, ttl_seconds)
        self._capacity = max(1, capacity)
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._grants: dict[str, _Grant] = {}

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @property
    def process_secret(self) -> bytes:
        return self._secret

    def _cleanup(self) -> None:
        now = self._clock()
        expired = [key for key, grant in self._grants.items() if grant.expires_at <= now]
        for key in expired:
            self._grants.pop(key, None)
        if len(self._grants) < self._capacity:
            return
        ordered = sorted(self._grants.items(), key=lambda item: item[1].issued_at)
        for key, _grant in ordered[: len(self._grants) - self._capacity + 1]:
            self._grants.pop(key, None)

    def issue(self, config: AIProviderConfig) -> tuple[str, str]:
        self._cleanup()
        token = self._token_factory()
        token_hash = self._hash_token(token)
        now = self._clock()
        expires_at_iso = (
            datetime.now(timezone.utc) + timedelta(seconds=self._ttl)
        ).isoformat()
        self._grants[token_hash] = _Grant(
            token_hash=token_hash,
            fingerprint=verification_fingerprint(config, self._secret),
            issued_at=now,
            expires_at=now + self._ttl,
            expires_at_iso=expires_at_iso,
        )
        return token, expires_at_iso

    def reserve(self, token: str, config: AIProviderConfig) -> str:
        token_hash = self._hash_token(token or "")
        grant = self._grants.get(token_hash)
        if grant is None:
            raise AIConfigurationError(
                "ai_test_required",
                "当前草稿没有可用的连接测试验证。",
            )
        if grant.expires_at <= self._clock():
            self._grants.pop(token_hash, None)
            raise AIConfigurationError("ai_test_expired", "草稿验证已过期。")
        if grant.state != "issued":
            raise AIConfigurationError("ai_test_used", "草稿验证已使用或正在使用。")
        expected = verification_fingerprint(config, self._secret)
        if not secrets.compare_digest(grant.fingerprint, expected):
            raise AIConfigurationError("ai_test_mismatch", "草稿字段与已验证配置不一致。")
        grant.state = "reserved"
        return token_hash

    def release(self, token_hash: str) -> None:
        grant = self._grants.get(token_hash)
        if grant is not None and grant.state == "reserved" and grant.expires_at > self._clock():
            grant.state = "issued"

    def consume(self, token_hash: str) -> None:
        grant = self._grants.get(token_hash)
        if grant is None or grant.state != "reserved":
            raise AIConfigurationError("ai_test_used", "草稿验证状态无效。")
        grant.state = "consumed"


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    existed: bool
    content: bytes


def _snapshot_file(path: Path) -> _FileSnapshot:
    try:
        return _FileSnapshot(True, path.read_bytes())
    except FileNotFoundError:
        return _FileSnapshot(False, b"")


def _current_matches(path: Path, snapshot: _FileSnapshot) -> bool:
    current = _snapshot_file(path)
    return current == snapshot


def _prepare_env_temp(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temp_path.chmod(0o600)
        except OSError:
            pass
        return temp_path
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _atomic_replace_env(
    path: Path,
    updates: dict[str, str | None],
    expected: _FileSnapshot,
) -> None:
    temp_path = _prepare_env_temp(path, expected.content)
    try:
        for key, value in updates.items():
            cleaned = clean_optional(value)
            if cleaned is None:
                unset_key(str(temp_path), key)
            else:
                set_key(str(temp_path), key, cleaned, quote_mode="auto")
        with temp_path.open("r+b") as handle:
            os.fsync(handle.fileno())
        if not _current_matches(path, expected):
            raise AIConfigurationError(
                "ai_settings_conflict",
                "AI 配置文件在保存期间发生变化。",
            )
        os.replace(temp_path, path)
        _fsync_parent_directory(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _restore_file(path: Path, snapshot: _FileSnapshot) -> None:
    if not snapshot.existed:
        path.unlink(missing_ok=True)
        return
    temp_path = _prepare_env_temp(path, snapshot.content)
    try:
        os.replace(temp_path, path)
        _fsync_parent_directory(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _fsync_parent_directory(path: Path) -> None:
    """Persist a completed rename where the platform supports directory fsync."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        directory_fd = os.open(path.parent, flags)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    except OSError:
        # Windows and some filesystems do not support fsync on directories.
        pass
    finally:
        os.close(directory_fd)


async def _close_provider(provider: object | None) -> BaseException | None:
    if provider is None:
        return None
    close = getattr(provider, "aclose", None)
    if callable(close):
        try:
            await close()
        except BaseException as exc:
            return exc
    return None


def _record_rollback_failure(
    failures: list[str],
    *,
    stage: str,
    exc: BaseException,
) -> None:
    failures.append(stage)
    logger.error(
        "AI settings rollback step failed: stage=%s exception_type=%s",
        stage,
        type(exc).__name__,
    )


def _attempt_rollback_step(
    failures: list[str],
    *,
    stage: str,
    action: Callable[[], None],
) -> None:
    try:
        action()
    except BaseException as exc:
        _record_rollback_failure(failures, stage=stage, exc=exc)


def _restore_environment(
    environment: MutableMapping[str, str],
    snapshot: dict[str, str | None],
    failures: list[str],
) -> None:
    for key, value in snapshot.items():
        try:
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        except BaseException as exc:
            _record_rollback_failure(failures, stage="environment", exc=exc)


async def _rollback_transaction(
    *,
    environment: MutableMapping[str, str],
    env_snapshot: dict[str, str | None],
    env_path: Path,
    file_snapshot: _FileSnapshot,
    file_committed: bool,
    restore_runtime_provider: Callable[[], None] | None = None,
    release_verification: Callable[[], None] | None = None,
    candidate: object | None = None,
) -> tuple[str, ...]:
    """Attempt every recovery action without letting one failure skip the rest."""

    failures: list[str] = []
    if restore_runtime_provider is not None:
        _attempt_rollback_step(
            failures,
            stage="runtime_provider",
            action=restore_runtime_provider,
        )
    if file_committed:
        _attempt_rollback_step(
            failures,
            stage="environment_file",
            action=lambda: _restore_file(env_path, file_snapshot),
        )
    _restore_environment(environment, env_snapshot, failures)
    if release_verification is not None:
        _attempt_rollback_step(
            failures,
            stage="verification",
            action=release_verification,
        )
    try:
        close_failure = await _close_provider(candidate)
    except BaseException as exc:
        _record_rollback_failure(failures, stage="candidate_provider", exc=exc)
    else:
        if close_failure is not None:
            _record_rollback_failure(
                failures,
                stage="candidate_provider",
                exc=close_failure,
            )
    return tuple(dict.fromkeys(failures))


async def _retire_provider(provider: object, delay: float) -> None:
    await asyncio.sleep(delay)
    await _close_provider(provider)


class AISettingsService:
    def __init__(
        self,
        *,
        environment: MutableMapping[str, str] | None = None,
        env_path: Path | None = None,
        install_secret_path: Path | None = None,
        resolver: Resolver | None = None,
        provider_builder: Callable[..., AIProvider] = build_provider,
        verification_store: VerificationStore | None = None,
        assessment_loader: Callable[[str], dict[str, Any] | None] = load_assessment,
        assessment_saver: Callable[[str, dict[str, Any]], None] = save_assessment,
    ) -> None:
        self.environment = os.environ if environment is None else environment
        self.env_path = env_path or DEFAULT_ENV_PATH
        self.install_secret_path = install_secret_path
        self.resolver = resolver
        self.provider_builder = provider_builder
        self.verifications = verification_store or VerificationStore()
        self.assessment_loader = assessment_loader
        self.assessment_saver = assessment_saver
        self._install_secret_cache: bytes | None = None

    def _install_secret(self) -> bytes:
        if self._install_secret_cache is None:
            self._install_secret_cache = load_or_create_install_secret(self.install_secret_path)
        return self._install_secret_cache

    @staticmethod
    def _payload(request: object) -> dict[str, Any]:
        if isinstance(request, dict):
            return dict(request)
        dump = getattr(request, "model_dump", None)
        if callable(dump):
            return dump()
        raise TypeError("AI settings request must be a mapping or pydantic model")

    def _existing_secret(self, provider: str) -> str | None:
        spec = provider_spec(provider)
        for name in (spec.api_key_env, *spec.legacy_api_key_envs):
            value = clean_optional(self.environment.get(name))
            if value:
                return value
        return None

    def normalize_draft(self, request: object, *, placeholder_model: bool = False) -> AIProviderConfig:
        payload = self._payload(request)
        provider = normalize_provider_name(payload.get("provider"))
        try:
            current_provider = normalize_provider_name(self.environment.get("AI_PROVIDER"))
        except AIConfigurationError:
            current_provider = None
        if placeholder_model and not clean_optional(payload.get("model")):
            payload["model"] = "__model_list_only__"
        return normalize_ai_config(
            provider=provider,
            provider_type=payload.get("provider_type"),
            api_key=payload.get("api_key"),
            base_url=payload.get("base_url"),
            model=payload.get("model"),
            simple_model=payload.get("simple_model"),
            enable_thinking=payload.get("enable_thinking") or False,
            enable_thinking_simple=payload.get("enable_thinking_simple") or False,
            thinking_config=payload.get("thinking_config"),
            thinking_config_simple=payload.get("thinking_config_simple"),
            current_provider=current_provider,
            current_api_key=self._existing_secret(provider),
        )

    def _provider_options(self, selected: str) -> list[str]:
        options = ["openai", "google", "h", "Z"]
        for item in (self.environment.get("AI_CUSTOM_PROVIDERS") or "").split(","):
            value = item.strip()
            if value and value not in options:
                options.append(value)
        if selected not in options:
            options.append(selected)
        return options

    def _raw_json(self, name: str) -> dict[str, str | bool | int] | None:
        import json

        raw = clean_optional(self.environment.get(name))
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(value, dict):
            return None
        safe: dict[str, str | bool | int] = {}
        for key, item in value.items():
            if isinstance(key, str) and (
                isinstance(item, bool) or isinstance(item, (str, int))
            ):
                safe[key] = item
        return dict(sorted(safe.items())) or None

    def current_settings(self, provider_name: str | None = None) -> dict[str, Any]:
        selected = normalize_provider_name(
            provider_name or self.environment.get("AI_PROVIDER") or "openai",
        )
        spec = provider_spec(selected)
        key = self._existing_secret(selected)
        base = clean_optional(self.environment.get(spec.base_url_env)) or spec.default_base_url or ""
        model = clean_optional(self.environment.get(spec.model_env))
        if model is None:
            for legacy in spec.legacy_model_envs:
                model = clean_optional(self.environment.get(legacy))
                if model:
                    break
        simple_model = clean_optional(self.environment.get(spec.simple_model_env))
        raw_type = self.environment.get(spec.provider_type_env)
        try:
            provider_type = normalize_provider_type(selected, raw_type)
        except AIConfigurationError:
            provider_type = (clean_optional(raw_type) or "openai").lower()
        active_name = clean_optional(self.environment.get("AI_PROVIDER"))
        effective = False
        status = "configuration_required"
        config: AIProviderConfig | None = None
        if active_name and normalize_provider_name(active_name) == selected:
            try:
                config = load_effective_ai_config(
                    self.environment,
                    install_secret=self._install_secret(),
                )
                effective = True
                status = "effective"
            except AIConfigurationError as exc:
                status = (
                    "configuration_invalid"
                    if exc.error_code == "ai_configuration_invalid"
                    else "configuration_required"
                )
        if config is None and key and model and base:
            try:
                config = normalize_ai_config(
                    provider=selected,
                    provider_type=provider_type,
                    api_key=key,
                    base_url=base,
                    model=model,
                    simple_model=simple_model,
                    enable_thinking=(self.environment.get(spec.enable_thinking_env) or "").lower()
                    in {"1", "true", "yes", "on"},
                    enable_thinking_simple=(
                        self.environment.get(spec.enable_thinking_simple_env) or ""
                    ).lower()
                    in {"1", "true", "yes", "on"},
                    thinking_config=self._raw_json(spec.thinking_config_env),
                    thinking_config_simple=self._raw_json(spec.thinking_config_simple_env),
                )
            except AIConfigurationError:
                config = None
        sources = {
            "provider": "saved" if active_name else "missing",
            "api_key": "saved" if clean_optional(self.environment.get(spec.api_key_env)) else (
                "legacy_env" if key else "missing"
            ),
            "base_url": "saved" if clean_optional(self.environment.get(spec.base_url_env)) else (
                "provider_default" if spec.default_base_url else "legacy_env" if base else "missing"
            ),
            "model": "saved" if clean_optional(self.environment.get(spec.model_env)) else (
                "legacy_env" if model else "missing"
            ),
            "simple_model": "saved" if simple_model else "missing",
            "provider_type": "saved" if clean_optional(raw_type) else "provider_default",
        }
        assessment = None
        if effective and config is not None:
            report = self.assessment_loader(
                assessment_fingerprint(config, self._install_secret()),
            )
            if report is not None and report.get("validator_version") == VALIDATOR_VERSION:
                assessment = dict(report)
                assessment["config_matches"] = True
        return {
            "provider": selected,
            "provider_type": provider_type,
            "api_key": SECRET_MASK if key else "",
            "base_url": base,
            "model": model or "",
            "simple_model": simple_model,
            "enable_thinking": (self.environment.get(spec.enable_thinking_env) or "").lower()
            in {"1", "true", "yes", "on"},
            "enable_thinking_simple": (
                self.environment.get(spec.enable_thinking_simple_env) or ""
            ).lower()
            in {"1", "true", "yes", "on"},
            "thinking_config": self._raw_json(spec.thinking_config_env),
            "thinking_config_simple": self._raw_json(spec.thinking_config_simple_env),
            "provider_options": self._provider_options(selected),
            "sources": sources,
            "effective": effective,
            "status": status,
            "assessment": assessment,
        }

    async def test_draft(self, request: object) -> dict[str, Any]:
        request_id = new_request_id()
        started = time.monotonic()
        provider: AIProvider | None = None
        try:
            config = self.normalize_draft(request)
            await resolve_public_endpoint(
                config.base_url,
                provider=config.provider,
                resolver=self.resolver,
            )
            provider = self.provider_builder(
                config,
                SINGLE_ATTEMPT,
                resolver=self.resolver,
            )
            await provider.probe_generation_once()
            token, expires_at = self.verifications.issue(config)
            return {
                "ok": True,
                "message": "实际生成可用，当前草稿已验证。",
                "latency_ms": round((time.monotonic() - started) * 1000),
                "request_id": request_id,
                "verification_token": token,
                "expires_at": expires_at,
                "verified_config": config.public_identity(),
            }
        except asyncio.CancelledError:
            raise
        except (AIConfigurationError, UnsafeEndpointError):
            raise
        except Exception as exc:
            raise provider_failure_from_exception(exc, request_id=request_id) from None
        finally:
            await _close_provider(provider)

    async def assess_draft(self, request: object) -> dict[str, Any]:
        request_id = new_request_id()
        provider: AIProvider | None = None
        try:
            config = self.normalize_draft(request)
            await resolve_public_endpoint(
                config.base_url,
                provider=config.provider,
                resolver=self.resolver,
            )
            provider = self.provider_builder(
                config,
                SINGLE_ATTEMPT,
                resolver=self.resolver,
            )
            report = await run_capability_assessment(provider)
            report.update(
                {
                    "provider": config.provider,
                    "provider_type": config.provider_type,
                    "model": config.model,
                },
            )
            fingerprint = assessment_fingerprint(config, self._install_secret())
            self.assessment_saver(fingerprint, report)
            response = dict(report)
            response.update({"request_id": request_id, "config_matches": True})
            return response
        except asyncio.CancelledError:
            raise
        except (AIConfigurationError, UnsafeEndpointError):
            raise
        except Exception as exc:
            raise provider_failure_from_exception(exc, request_id=request_id) from None
        finally:
            await _close_provider(provider)

    async def list_models(self, request: object) -> dict[str, Any]:
        request_id = new_request_id()
        config = self.normalize_draft(request, placeholder_model=True)
        try:
            await resolve_public_endpoint(
                config.base_url,
                provider=config.provider,
                resolver=self.resolver,
            )
            async with create_safe_async_client(
                config.base_url,
                resolver=self.resolver,
                timeout=12.0,
            ) as client:
                if config.provider_type == "google":
                    response = await client.get(
                        f"{config.base_url.rstrip('/')}/v1beta/models",
                        params={"key": config.api_key},
                    )
                    response.raise_for_status()
                    models = {
                        str(item.get("name", "")).split("/", 1)[-1].strip()
                        for item in (response.json().get("models") or [])
                        if isinstance(item, dict) and str(item.get("name", "")).strip()
                    }
                    source = "google-api"
                elif config.provider_type == "anthropic":
                    response = await client.get(
                        f"{config.base_url.rstrip('/')}/v1/models",
                        headers={
                            "x-api-key": config.api_key,
                            "anthropic-version": "2023-06-01",
                        },
                    )
                    response.raise_for_status()
                    models = {
                        str(item.get("id", "")).strip()
                        for item in (response.json().get("data") or [])
                        if isinstance(item, dict) and str(item.get("id", "")).strip()
                    }
                    source = "anthropic-api"
                else:
                    response = await client.get(
                        f"{config.base_url.rstrip('/')}/models",
                        headers={"Authorization": f"Bearer {config.api_key}"},
                    )
                    response.raise_for_status()
                    models = {
                        str(item.get("id", "")).strip()
                        for item in (response.json().get("data") or [])
                        if isinstance(item, dict) and str(item.get("id", "")).strip()
                    }
                    source = "openai-compatible"
            return {"provider": config.provider, "models": sorted(models), "source": source}
        except (AIConfigurationError, UnsafeEndpointError):
            raise
        except Exception as exc:
            raise provider_failure_from_exception(exc, request_id=request_id) from None

    async def apply_draft(
        self,
        request: object,
        *,
        get_runtime_provider: Callable[[], object | None],
        set_runtime_provider: Callable[[object | None], None],
    ) -> dict[str, Any]:
        request_id = new_request_id()
        payload = self._payload(request)
        token = str(payload.pop("verification_token", ""))
        config = self.normalize_draft(payload)
        await resolve_public_endpoint(
            config.base_url,
            provider=config.provider,
            resolver=self.resolver,
        )
        reservation = self.verifications.reserve(token, config)
        candidate: AIProvider | None = None
        old_provider = get_runtime_provider()
        file_snapshot = _snapshot_file(self.env_path)
        updates: dict[str, str | None] = {}
        env_snapshot: dict[str, str | None] = {}
        file_committed = False
        slot_change_attempted = False
        try:
            candidate = self.provider_builder(config, RUNTIME, resolver=self.resolver)
            install_secret = self._install_secret()
            updates = config_env_updates(config, install_secret)
            if config.provider not in PROVIDER_SPECS:
                existing = [
                    item.strip()
                    for item in (self.environment.get("AI_CUSTOM_PROVIDERS") or "").split(",")
                    if item.strip()
                ]
                if config.provider not in existing:
                    existing.append(config.provider)
                updates["AI_CUSTOM_PROVIDERS"] = ",".join(existing)
            env_snapshot = {key: self.environment.get(key) for key in updates}
            _atomic_replace_env(self.env_path, updates, file_snapshot)
            file_committed = True
            for key, value in updates.items():
                cleaned = clean_optional(value)
                if cleaned is None:
                    self.environment.pop(key, None)
                else:
                    self.environment[key] = cleaned
            slot_change_attempted = True
            set_runtime_provider(candidate)
            response = self.current_settings(config.provider)
            self.verifications.consume(reservation)
            if old_provider is not None and old_provider is not candidate:
                asyncio.create_task(
                    _retire_provider(old_provider, RUNTIME_RETIRE_GRACE_SECONDS),
                )
            return response
        except BaseException as exc:
            rollback_failures = await _rollback_transaction(
                environment=self.environment,
                env_snapshot=env_snapshot,
                env_path=self.env_path,
                file_snapshot=file_snapshot,
                file_committed=file_committed,
                restore_runtime_provider=(
                    lambda: set_runtime_provider(old_provider)
                    if slot_change_attempted
                    else None
                ),
                release_verification=lambda: self.verifications.release(reservation),
                candidate=candidate,
            )
            if rollback_failures:
                raise ProviderFailure(
                    error_code="ai_settings_rollback_failed",
                    request_id=request_id,
                ) from exc
            if isinstance(
                exc,
                (AIConfigurationError, UnsafeEndpointError, ProviderFailure),
            ):
                raise
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, Exception):
                raise ProviderFailure(
                    error_code="ai_settings_apply_failed",
                    request_id=request_id,
                ) from exc
            raise

    async def delete_settings(
        self,
        provider_name: str,
        *,
        get_runtime_provider: Callable[[], object | None],
        set_runtime_provider: Callable[[object | None], None],
    ) -> dict[str, Any]:
        request_id = new_request_id()
        provider = normalize_provider_name(provider_name)
        spec = provider_spec(provider)
        updates: dict[str, str | None] = {
            spec.api_key_env: None,
            spec.base_url_env: None,
            spec.model_env: None,
            spec.simple_model_env: None,
            spec.provider_type_env: None,
            spec.enable_thinking_env: None,
            spec.enable_thinking_simple_env: None,
            spec.thinking_config_env: None,
            spec.thinking_config_simple_env: None,
        }
        custom = [
            item.strip()
            for item in (self.environment.get("AI_CUSTOM_PROVIDERS") or "").split(",")
            if item.strip() and item.strip() != provider
        ]
        updates["AI_CUSTOM_PROVIDERS"] = ",".join(custom) if custom else None
        active = clean_optional(self.environment.get("AI_PROVIDER"))
        deleting_active = bool(active and normalize_provider_name(active) == provider)
        if deleting_active:
            updates.update(
                {
                    "AI_PROVIDER": None,
                    EFFECTIVE_PROOF_ENV: None,
                    EFFECTIVE_PROOF_VERSION_ENV: None,
                },
            )
        snapshot = _snapshot_file(self.env_path)
        env_snapshot = {key: self.environment.get(key) for key in updates}
        old_provider = get_runtime_provider()
        file_committed = False
        slot_change_attempted = False
        try:
            _atomic_replace_env(self.env_path, updates, snapshot)
            file_committed = True
            for key, value in updates.items():
                if value is None:
                    self.environment.pop(key, None)
                else:
                    self.environment[key] = value
            if deleting_active:
                slot_change_attempted = True
                set_runtime_provider(None)
            response = self.current_settings("openai" if deleting_active else provider)
            if deleting_active and old_provider is not None:
                asyncio.create_task(_retire_provider(old_provider, 0.0))
            return response
        except BaseException as exc:
            rollback_failures = await _rollback_transaction(
                environment=self.environment,
                env_snapshot=env_snapshot,
                env_path=self.env_path,
                file_snapshot=snapshot,
                file_committed=file_committed,
                restore_runtime_provider=(
                    lambda: set_runtime_provider(old_provider)
                    if slot_change_attempted
                    else None
                ),
            )
            if rollback_failures:
                raise ProviderFailure(
                    error_code="ai_settings_rollback_failed",
                    request_id=request_id,
                ) from exc
            if isinstance(exc, (AIConfigurationError, ProviderFailure)):
                raise
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, Exception):
                raise ProviderFailure(
                    error_code="ai_settings_apply_failed",
                    request_id=request_id,
                ) from exc
            raise


_service: AISettingsService | None = None


def get_ai_settings_service() -> AISettingsService:
    global _service
    if _service is None:
        _service = AISettingsService()
    return _service


def set_ai_settings_service_for_testing(service: AISettingsService | None) -> None:
    global _service
    _service = service
