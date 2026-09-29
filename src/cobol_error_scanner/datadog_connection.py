"""Datadog connection.

Loads site and credentials from the environment and checks that Datadog accepts
them. This module does not search logs and does not change the Jira workflow.

    DATADOG_API_KEY     Datadog API key
    DATADOG_APP_KEY     Datadog application key
    DATADOG_SITE        optional site, default datadoghq.com
                        (us3.datadoghq.com, us5.datadoghq.com, datadoghq.eu, …)
    DATADOG_TIMEOUT     optional request timeout seconds, default 15
    DATADOG_VERIFY_SSL  optional, "0" to disable TLS verification
    DATADOG_MOCK        optional, "1" to report a successful connection without
                        calling Datadog

Authentication uses the DD-API-KEY and DD-APPLICATION-KEY headers.
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


@dataclass
class DatadogConfig:
    api_key: str = ""
    app_key: str = ""
    site: str = "datadoghq.com"
    timeout: float = 15.0
    verify_ssl: bool = True
    mock: str = ""

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "DatadogConfig":
        src = env if env is not None else os.environ
        try:
            timeout = float(str(src.get("DATADOG_TIMEOUT", "15")).strip() or "15")
        except ValueError:
            timeout = 15.0
        verify_ssl = str(src.get("DATADOG_VERIFY_SSL", "1")).strip() not in {"0", "false", "False"}
        return cls(
            api_key=str(src.get("DATADOG_API_KEY", "")).strip(),
            app_key=str(src.get("DATADOG_APP_KEY", "")).strip(),
            site=normalize_site(str(src.get("DATADOG_SITE", "datadoghq.com"))),
            timeout=timeout,
            verify_ssl=verify_ssl,
            mock=str(src.get("DATADOG_MOCK", "")).strip(),
        )

    @property
    def is_mock(self) -> bool:
        return bool(self.mock)

    @property
    def is_configured(self) -> bool:
        if self.is_mock:
            return True
        return bool(self.api_key and self.app_key)

    @property
    def api_base(self) -> str:
        return api_origin(self.site)

    def public_dict(self) -> dict[str, Any]:
        """Non-secret summary. API and application keys are omitted."""
        return {
            "configured": self.is_configured,
            "site": self.site,
            "api_host": self.api_base,
            "mock": self.is_mock,
        }


def _ssl_context(config: DatadogConfig) -> ssl.SSLContext | None:
    if config.verify_ssl:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _get_json(config: DatadogConfig, path: str) -> dict[str, Any]:
    url = config.api_base.rstrip("/") + "/" + path.lstrip("/")
    request = urllib.request.Request(url, method="GET")
    request.add_header("DD-API-KEY", config.api_key)
    request.add_header("DD-APPLICATION-KEY", config.app_key)
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(
            request, timeout=config.timeout, context=_ssl_context(config)
        ) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:500]
        except Exception:
            pass
        raise DatadogConnectionError(
            f"Datadog returned HTTP {exc.code} for {path}. {detail}".strip()
        ) from exc
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


def connect(config: DatadogConfig | None = None) -> dict[str, Any]:
    """Check that the configured Datadog site accepts the API and application keys.

    Returns a status dict and never includes the key values. ``connected`` is
    true only when Datadog reports the API key valid and the application key
    can read the current user, or when ``DATADOG_MOCK`` is set.
    """
    cfg = config or DatadogConfig.from_env()
    status: dict[str, Any] = {
        **cfg.public_dict(),
        "connected": False,
        "api_key_valid": False,
    }
    if not cfg.is_configured:
        status["error"] = (
            "Datadog is not configured. Set DATADOG_API_KEY and DATADOG_APP_KEY."
        )
        return status

    if cfg.is_mock:
        status["connected"] = True
        status["api_key_valid"] = True
        return status

    try:
        validation = _get_json(cfg, _VALIDATE_PATH)
        status["api_key_valid"] = bool(validation.get("valid"))
        if not status["api_key_valid"]:
            status["error"] = "Datadog rejected the API key."
            return status
        _get_json(cfg, _CURRENT_USER_PATH)
    except DatadogConnectionError as exc:
        status["error"] = str(exc)
        return status

    status["connected"] = True
    return status
