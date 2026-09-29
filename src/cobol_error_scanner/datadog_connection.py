"""Datadog connection.

Loads site and credentials from the environment and checks that Datadog accepts
them. This module does not search logs and does not change the Jira workflow.

    DD_ACCESS_TOKEN     Datadog personal or service access token (preferred)
    DATADOG_ACCESS_TOKEN  same as DD_ACCESS_TOKEN
    DD_SITE / DATADOG_SITE  optional site, default datadoghq.com
                        (us3.datadoghq.com, us5.datadoghq.com, datadoghq.eu, …)
    DATADOG_API_KEY     Datadog API key, used only when no access token is set
    DATADOG_APP_KEY     Datadog application key, paired with the API key
    DD_API_KEY / DD_APP_KEY  same as the DATADOG_* key pair
    DATADOG_TIMEOUT     optional request timeout seconds, default 15
    DATADOG_VERIFY_SSL  optional, "0" to disable TLS verification
    DATADOG_MOCK        optional, "1" to report a successful connection without
                        calling Datadog

An access token is sent as ``Authorization: Bearer``. It is not paired with an
API key. Key-pair auth uses the DD-API-KEY and DD-APPLICATION-KEY headers.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

_VALIDATE_PATH = "/api/v1/validate"
_CURRENT_USER_PATH = "/api/v2/current_user"
_LOGS_PROBE_PATH = "/api/v2/logs/events?filter[query]=*&page[limit]=1"

# site token -> API origin
_SITES: dict[str, str] = {
    "datadoghq.com": "https://api.datadoghq.com",
    "us3.datadoghq.com": "https://api.us3.datadoghq.com",
    "us5.datadoghq.com": "https://api.us5.datadoghq.com",
    "datadoghq.eu": "https://api.datadoghq.eu",
    "ap1.datadoghq.com": "https://api.ap1.datadoghq.com",
    "ap2.datadoghq.com": "https://api.ap2.datadoghq.com",
    "uk1.datadoghq.com": "https://api.uk1.datadoghq.com",
    "ddog-gov.com": "https://api.ddog-gov.com",
    "us2.ddog-gov.com": "https://api.us2.ddog-gov.com",
}


class DatadogConnectionError(Exception):
    """Raised when Datadog rejects the credentials or cannot be reached."""


class DatadogHTTPError(DatadogConnectionError):
    """HTTP response from Datadog that is not a successful JSON body."""

    def __init__(self, status: int, path: str, detail: str) -> None:
        self.status = status
        self.path = path
        self.detail = detail
        super().__init__(f"Datadog returned HTTP {status} for {path}. {detail}".strip())


def normalize_site(raw: str) -> str:
    """Reduce a site, app host, or URL to a Datadog site token."""
    text = (raw or "").strip().lower()
    text = text.removeprefix("https://").removeprefix("http://")
    text = text.split("/")[0].strip().strip(".")
    if text.startswith("app."):
        text = text[4:]
    if text.startswith("api."):
        text = text[4:]
    return text or "datadoghq.com"


def api_origin(site: str) -> str:
    token = normalize_site(site)
    return _SITES.get(token, f"https://api.{token}")


def _first(src: dict[str, str], *names: str) -> str:
    for name in names:
        value = str(src.get(name, "")).strip()
        if value:
            return value
    return ""


@dataclass
class DatadogConfig:
    api_key: str = ""
    app_key: str = ""
    access_token: str = ""
    site: str = "datadoghq.com"
    timeout: float = 15.0
    verify_ssl: bool = True
    mock: str = ""

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "DatadogConfig":
        src = env if env is not None else os.environ
        try:
            timeout = float(str(src.get("DATADOG_TIMEOUT", src.get("DD_TIMEOUT", "15"))).strip() or "15")
        except ValueError:
            timeout = 15.0
        verify_raw = _first(src, "DATADOG_VERIFY_SSL", "DD_VERIFY_SSL") or "1"
        verify_ssl = verify_raw.strip() not in {"0", "false", "False"}
        site = _first(src, "DATADOG_SITE", "DD_SITE") or "datadoghq.com"
        return cls(
            api_key=_first(src, "DATADOG_API_KEY", "DD_API_KEY"),
            app_key=_first(src, "DATADOG_APP_KEY", "DD_APP_KEY"),
            access_token=_first(src, "DD_ACCESS_TOKEN", "DATADOG_ACCESS_TOKEN"),
            site=normalize_site(site),
            timeout=timeout,
            verify_ssl=verify_ssl,
            mock=_first(src, "DATADOG_MOCK", "DD_MOCK"),
        )

    @property
    def is_mock(self) -> bool:
        return bool(self.mock)

    @property
    def uses_access_token(self) -> bool:
        return bool(self.access_token)

    @property
    def is_configured(self) -> bool:
        if self.is_mock:
            return True
        if self.access_token:
            return True
        return bool(self.api_key and self.app_key)

    @property
    def api_base(self) -> str:
        return api_origin(self.site)

    def public_dict(self) -> dict[str, Any]:
        """Non-secret summary. API and application keys are omitted."""
        if self.access_token:
            auth = "access_token"
        elif self.api_key and self.app_key:
            auth = "api_key"
        else:
            auth = ""
        return {
            "configured": self.is_configured,
            "site": self.site,
            "api_host": self.api_base,
            "auth": auth,
            "mock": self.is_mock,
        }


def _ssl_context(config: DatadogConfig) -> ssl.SSLContext | None:
    if config.verify_ssl:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _auth_headers(config: DatadogConfig) -> list[tuple[str, str]]:
    if config.access_token:
        return [("Authorization", f"Bearer {config.access_token}")]
    return [
        ("DD-API-KEY", config.api_key),
        ("DD-APPLICATION-KEY", config.app_key),
    ]


def _request_json(
    config: DatadogConfig,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    url = config.api_base.rstrip("/") + "/" + path.lstrip("/")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST" if payload is not None else "GET")
    for name, value in _auth_headers(config):
        request.add_header(name, value)
    request.add_header("Accept", "application/json")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(
            request, timeout=timeout if timeout is not None else config.timeout, context=_ssl_context(config)
        ) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:500]
        except Exception:
            pass
        raise DatadogHTTPError(exc.code, path.split("?", 1)[0], detail) from exc
    except urllib.error.URLError as exc:
        raise DatadogConnectionError(
            f"Could not reach Datadog at {config.api_base}: {exc.reason}"
        ) from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise DatadogConnectionError("Datadog returned a non-JSON response.") from exc
    if not isinstance(parsed, dict):
        raise DatadogConnectionError("Datadog returned an unexpected response.")
    return parsed


def _get_json(config: DatadogConfig, path: str) -> dict[str, Any]:
    return _request_json(config, path)


def _scrub(config: DatadogConfig, text: str) -> str:
    for secret in (config.access_token, config.api_key, config.app_key):
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def _connect_with_access_token(config: DatadogConfig, status: dict[str, Any]) -> dict[str, Any]:
    """Confirm a personal or service access token against the logs API.

    A 200 means the token can read logs. A permission failure means Datadog
    accepted the token but this token's scopes do not include logs.
    """
    try:
        _get_json(config, _LOGS_PROBE_PATH)
    except DatadogHTTPError as exc:
        detail = _scrub(config, exc.detail)
        if exc.status == 403 and "permission" in detail.lower():
            status["authenticated"] = True
            status["error"] = (
                "Datadog accepted the access token, but it cannot read logs."
            )
            return status
        status["error"] = _scrub(config, str(exc))
        return status
    except DatadogConnectionError as exc:
        status["error"] = _scrub(config, str(exc))
        return status
    status["connected"] = True
    status["scope"] = "logs"
    return status


def _connect_with_api_keys(config: DatadogConfig, status: dict[str, Any]) -> dict[str, Any]:
    try:
        validation = _get_json(config, _VALIDATE_PATH)
        status["api_key_valid"] = bool(validation.get("valid"))
        if not status["api_key_valid"]:
            status["error"] = "Datadog rejected the API key."
            return status
        _get_json(config, _CURRENT_USER_PATH)
    except DatadogConnectionError as exc:
        status["error"] = _scrub(config, str(exc))
        return status
    status["connected"] = True
    return status


def connect(config: DatadogConfig | None = None) -> dict[str, Any]:
    """Check that Datadog accepts the configured access token or key pair.

    An access token, when set, is preferred over API and application keys.
    The returned status never includes credential values. ``connected`` is
    true when the token can read logs, when the API key validates and the
    application key can read the current user, or when mock mode is set.
    """
    cfg = config or DatadogConfig.from_env()
    status: dict[str, Any] = {
        **cfg.public_dict(),
        "connected": False,
        "api_key_valid": False,
    }
    if not cfg.is_configured:
        status["error"] = (
            "Datadog is not configured. Set DD_ACCESS_TOKEN, or "
            "DATADOG_API_KEY and DATADOG_APP_KEY."
        )
        return status

    if cfg.is_mock:
        status["connected"] = True
        status["api_key_valid"] = not cfg.uses_access_token
        return status

    if cfg.uses_access_token:
        return _connect_with_access_token(cfg, status)
    return _connect_with_api_keys(cfg, status)
