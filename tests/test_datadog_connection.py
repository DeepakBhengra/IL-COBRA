"""Tests for the Datadog connection module (offline, no live Datadog calls)."""

from __future__ import annotations

import io
import json

from cobol_error_scanner import datadog_connection as datadog
from cobol_error_scanner.datadog_connection import DatadogConfig, connect


def test_normalize_site_strips_app_host_and_scheme():
    assert datadog.normalize_site("https://app.datadoghq.eu/logs") == "datadoghq.eu"
    assert datadog.normalize_site("app.us5.datadoghq.com") == "us5.datadoghq.com"
    assert datadog.normalize_site("") == "datadoghq.com"


def test_api_origin_for_eu_site():
    assert datadog.api_origin("datadoghq.eu") == "https://api.datadoghq.eu"


def test_connect_reports_missing_credentials():
    status = connect(DatadogConfig())
    assert status["configured"] is False
    assert status["connected"] is False
    assert "DD_ACCESS_TOKEN" in status["error"]
    assert "DATADOG_API_KEY" in status["error"]
    assert "api_key" not in status
    assert "access_token" not in status


def test_config_from_env_hides_secrets(monkeypatch):
    monkeypatch.setenv("DATADOG_API_KEY", "dd-api-secret")
    monkeypatch.setenv("DATADOG_APP_KEY", "dd-app-secret")
    monkeypatch.setenv("DATADOG_SITE", "https://app.datadoghq.eu")
    cfg = DatadogConfig.from_env()
    assert cfg.is_configured is True
    assert cfg.site == "datadoghq.eu"
    assert cfg.api_base == "https://api.datadoghq.eu"
    dumped = json.dumps(cfg.public_dict())
    assert "dd-api-secret" not in dumped
    assert "dd-app-secret" not in dumped


def test_config_from_env_prefers_dd_access_token(monkeypatch):
    monkeypatch.setenv("DD_ACCESS_TOKEN", "ddpat_secret")
    monkeypatch.setenv("DD_API_KEY", "dd-api-secret")
    monkeypatch.setenv("DD_APP_KEY", "dd-app-secret")
    monkeypatch.setenv("DD_SITE", "us5.datadoghq.com")
    cfg = DatadogConfig.from_env()
    assert cfg.uses_access_token is True
    assert cfg.site == "us5.datadoghq.com"
    assert cfg.api_base == "https://api.us5.datadoghq.com"
    public = cfg.public_dict()
    assert public["auth"] == "access_token"
    dumped = json.dumps(public)
    assert "ddpat_secret" not in dumped
    assert "dd-api-secret" not in dumped
    assert "dd-app-secret" not in dumped


def test_connect_mock_skips_network():
    status = connect(DatadogConfig(mock="1"))
    assert status["configured"] is True
    assert status["connected"] is True
    assert status["mock"] is True
    assert status["api_key_valid"] is True


def test_connect_live_checks_api_key_then_application_key(monkeypatch):
    cfg = DatadogConfig(
        api_key="dd-api-secret",
        app_key="dd-app-secret",
        site="us5.datadoghq.com",
    )
    calls: list[str] = []

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None, context=None):  # noqa: ANN001
        calls.append(request.full_url)
        assert request.get_header("Dd-api-key") == "dd-api-secret"
        assert request.get_header("Dd-application-key") == "dd-app-secret"
        if request.full_url.endswith("/api/v1/validate"):
            payload = {"valid": True}
        else:
            payload = {"data": {"type": "users", "id": "abc"}}
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(datadog.urllib.request, "urlopen", fake_urlopen)
    status = connect(cfg)

    assert calls == [
        "https://api.us5.datadoghq.com/api/v1/validate",
        "https://api.us5.datadoghq.com/api/v2/current_user",
    ]
    assert status["connected"] is True
    assert status["api_key_valid"] is True
    dumped = json.dumps(status)
    assert "dd-api-secret" not in dumped
    assert "dd-app-secret" not in dumped


def test_connect_stops_when_api_key_is_invalid(monkeypatch):
    cfg = DatadogConfig(api_key="bad", app_key="app", site="datadoghq.com")
    calls: list[str] = []

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None, context=None):  # noqa: ANN001
        calls.append(request.full_url)
        return FakeResponse(json.dumps({"valid": False}).encode("utf-8"))

    monkeypatch.setattr(datadog.urllib.request, "urlopen", fake_urlopen)
    status = connect(cfg)
    assert calls == ["https://api.datadoghq.com/api/v1/validate"]
    assert status["connected"] is False
    assert status["api_key_valid"] is False
    assert "rejected" in status["error"].lower()


def test_connect_access_token_probes_logs(monkeypatch):
    cfg = DatadogConfig(
        access_token="ddpat_secret",
        api_key="dd-api-secret",
        app_key="dd-app-secret",
        site="us5.datadoghq.com",
    )
    calls: list[str] = []

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None, context=None):  # noqa: ANN001
        calls.append(request.full_url)
        assert request.get_header("Authorization") == "Bearer ddpat_secret"
        assert request.get_header("Dd-api-key") is None
        assert request.get_header("Dd-application-key") is None
        return FakeResponse(json.dumps({"data": []}).encode("utf-8"))

    monkeypatch.setattr(datadog.urllib.request, "urlopen", fake_urlopen)
    status = connect(cfg)

    assert calls == [
        "https://api.us5.datadoghq.com/api/v2/logs/events?filter[query]=*&page[limit]=1"
    ]
    assert status["connected"] is True
    assert status["auth"] == "access_token"
    assert status["scope"] == "logs"
    dumped = json.dumps(status)
    assert "ddpat_secret" not in dumped
    assert "dd-api-secret" not in dumped


def test_connect_access_token_reports_permission_gap(monkeypatch):
    import urllib.error

    cfg = DatadogConfig(access_token="ddpat_secret", site="us5.datadoghq.com")

    def fake_urlopen(request, timeout=None, context=None):  # noqa: ANN001
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            hdrs=None,
            fp=io.BytesIO(
                b'{"errors":["Forbidden","Failed permission authorization checks"]}'
            ),
        )

    monkeypatch.setattr(datadog.urllib.request, "urlopen", fake_urlopen)
    status = connect(cfg)
    assert status["connected"] is False
    assert status["authenticated"] is True
    assert "cannot read logs" in status["error"]
    assert "ddpat_secret" not in json.dumps(status)
