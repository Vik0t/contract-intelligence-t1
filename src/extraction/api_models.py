"""Resolve model aliases without silently selecting a different model."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
import threading

import httpx

_aliases: dict[tuple[str, str], str] = {}
_clients: dict[tuple, httpx.Client] = {}
_client_lock = threading.Lock()


@contextmanager
def api_client():
    """Use explicit proxy opt-in and retry only connection establishment failures.

    Developer machines can inherit proxies that cannot reach an internal API.
    Certificate verification stays enabled; completed requests are not replayed.
    """
    trust_env = os.getenv("ML_API_TRUST_ENV", "false").lower() in {"true", "1", "yes"}
    retries = int(os.getenv("ML_API_CONNECT_RETRIES", "2"))
    if not 0 <= retries <= 3:
        raise ValueError("ML_API_CONNECT_RETRIES must be between 0 and 3")
    timeout = float(os.getenv("ML_API_TIMEOUT", "120"))
    config = (trust_env, retries, timeout)
    with _client_lock:
        if config not in _clients:
            _clients[config] = httpx.Client(
                timeout=httpx.Timeout(timeout, connect=10.0), trust_env=trust_env,
                transport=httpx.HTTPTransport(retries=retries, trust_env=trust_env,
                    limits=httpx.Limits(max_connections=8, max_keepalive_connections=4, keepalive_expiry=60)),
            )
        client = _clients[config]
    # Reuse TLS connections across extraction, summary and risks. httpx.Client
    # is thread-safe; credentials are supplied per request, never on the pool.
    yield client


def close_api_clients() -> None:
    with _client_lock:
        for client in _clients.values():
            client.close()
        _clients.clear()


def resolve_model(client: httpx.Client, base: str, key: str, requested: str, *, required: bool = False) -> str:
    cache_key = (base, requested)
    if not required and cache_key in _aliases:
        return _aliases[cache_key]
    try:
        response = client.get(
            f"{base}/models", headers={"Authorization": f"Bearer {key}"},
            timeout=httpx.Timeout(15.0, connect=5.0),
        )
        if response.status_code in {404, 405}:
            return requested  # Some compatible APIs expose completions only.
        response.raise_for_status()
        data = response.json().get("data", [])
    except (httpx.HTTPError, ValueError):
        if required:
            raise
        return requested
    ids = [item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)]
    matches = [name for name in ids if name == requested]
    if not matches:
        matches = [name for name in ids if name.casefold() == requested.casefold()]
    if len(matches) == 1:
        _aliases[cache_key] = matches[0]
        _aliases[(base, matches[0])] = matches[0]
        return matches[0]
    if required and ids:
        raise ValueError(f"Модель {requested!r} отсутствует в /models; укажите точный ID провайдера")
    return requested


def preflight_model(requested: str) -> str:
    base = os.getenv("OPENAI_BASE_URL", "").strip().rstrip("/")
    key = os.getenv("OPENAI_API_KEY", "")
    if not base or not key:
        raise ValueError("Нужны OPENAI_BASE_URL и OPENAI_API_KEY")
    with api_client() as client:
        return resolve_model(client, base, key, requested, required=True)


def safe_error_details(exc: Exception) -> dict:
    """Keep actionable provider messages, never headers, credentials or raw bodies."""
    details = {"error_type": type(exc).__name__}
    message = None
    if isinstance(exc, httpx.HTTPStatusError):
        details["http_status"] = exc.response.status_code
        try:
            payload = exc.response.json()
            error = payload.get("error", payload.get("detail")) if isinstance(payload, dict) else None
            message = error.get("message") if isinstance(error, dict) else error
        except ValueError:
            pass
    elif isinstance(exc, (ValueError, RuntimeError)):
        message = str(exc)
    if isinstance(message, str):
        for name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "HF_TOKEN"):
            secret = os.getenv(name)
            if secret:
                message = message.replace(secret, "[redacted]")
        message = re.sub(r"(?i)Bearer\s+\S+", "Bearer [redacted]", message)
        message = re.sub(r"https?://\S+", "[endpoint]", message)
        details["error_message"] = message[:500]
    return details
