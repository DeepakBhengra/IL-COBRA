"""Tests for Datadog log search (offline: mock mode + patched transport)."""

from __future__ import annotations

import io
import json

from cobol_error_scanner import datadog_integration as datadog
from cobol_error_scanner.datadog_integration import DatadogConfig, build_log_query


def test_normalize_site_strips_app_host_and_scheme():
    assert datadog.normalize_site("https://app.datadoghq.eu/logs") == "datadoghq.eu"
    assert datadog.normalize_site("app.us5.datadoghq.com") == "us5.datadoghq.com"
    assert datadog.normalize_site("") == "datadoghq.com"


def test_site_origins_known_eu_site():
    api, app = datadog.site_origins("datadoghq.eu")
    assert api == "https://api.datadoghq.eu"
    assert app == "https://app.datadoghq.eu"


def test_build_log_query_phrases_terms_and_extra():
    query = build_log_query(["ERR-NO-SEC-TERM-OVRD", "NO-SEC-TERM-OVRD"], "env:prod")
    assert '"ERR-NO-SEC-TERM-OVRD"' in query
    assert '"NO-SEC-TERM-OVRD"' in query
    assert query.endswith("env:prod")


def test_build_log_query_escapes_quotes():
    query = build_log_query(['AB"C'])
    assert '\\"' in query


def test_search_for_finding_not_configured():
    result = datadog.search_for_finding("SE", "CORORA-R-ERR-NO-SEC-TERM-OVRD", config=DatadogConfig())
    assert result["configured"] is False
    assert result["reachable"] is False
    assert "DATADOG_API_KEY" in result["error"]
    assert result["logs"] == []


def test_config_from_env_hides_secrets(monkeypatch):
    monkeypatch.setenv("DATADOG_API_KEY", "dd-api-secret")
    monkeypatch.setenv("DATADOG_APP_KEY", "dd-app-secret")
    monkeypatch.setenv("DATADOG_SITE", "https://app.datadoghq.eu")
    monkeypatch.setenv("DATADOG_LOOKBACK", "15m")
    monkeypatch.setenv("DATADOG_INDEXES", "main, cobol")
    cfg = DatadogConfig.from_env()
    assert cfg.is_configured is True
    assert cfg.site == "datadoghq.eu"
    assert cfg.lookback == "15m"
    assert cfg.indexes == ["main", "cobol"]
    assert cfg.api_base == "https://api.datadoghq.eu"
    public = cfg.public_dict()
    dumped = json.dumps(public)
    assert "dd-api-secret" not in dumped
    assert "dd-app-secret" not in dumped
    assert "api_key" not in public
    assert "app_key" not in public


def test_invalid_lookback_falls_back(monkeypatch):
    monkeypatch.setenv("DATADOG_LOOKBACK", "forever")
    assert DatadogConfig.from_env().lookback == "7d"


def test_search_for_finding_mock_filters_by_field():
    cfg = DatadogConfig(mock="1", site="datadoghq.com")
    result = datadog.search_for_finding("SE", "CORORA-R-ERR-NO-SEC-TERM-OVRD", config=cfg)
    assert result["configured"] is True
    assert result["reachable"] is True
    assert result["mock"] is True
    assert result["log_count"] >= 1
    ids = {item["id"] for item in result["logs"]}
    assert "log-se-1001" in ids
    assert "log-ev-2001" not in ids
    assert "error" in result["summary"].lower()
    assert result["logs"][0]["url"].startswith("https://app.datadoghq.com/logs?query=")


def test_search_for_finding_mock_no_match():
    cfg = DatadogConfig(mock="1")
    result = datadog.search_for_finding("ZZ", "NOTHING-MATCHES-THIS", config=cfg)
    assert result["log_count"] == 0
    assert "No Datadog logs" in result["summary"]


def test_search_live_path_sends_keys_and_query(monkeypatch):
    cfg = DatadogConfig(
        api_key="dd-api-secret",
        app_key="dd-app-secret",
        site="us5.datadoghq.com",
        extra_query="service:order-edit",
        lookback="4h",
    )
    captured: dict[str, object] = {}

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None, context=None):  # noqa: ANN001
        captured["url"] = request.full_url
        captured["api_key"] = request.get_header("Dd-api-key")
        captured["app_key"] = request.get_header("Dd-application-key")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        payload = {
            "data": [
                {
                    "id": "live-1",
                    "type": "log",
                    "attributes": {
                        "service": "order-edit",
                        "host": "bridge-9",
                        "status": "error",
                        "timestamp": "2026-04-01T00:00:00Z",
                        "message": "SE edit set ERR-NO-SEC-TERM-OVRD for account 17.",
                        "tags": ["env:prod"],
                    },
                },
                {
                    "id": "live-loose",
                    "type": "log",
                    "attributes": {
                        "service": "other",
                        "status": "info",
                        "message": "unrelated heartbeat",
                        "timestamp": "2026-04-01T00:00:01Z",
                    },
                },
            ]
        }
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(datadog.urllib.request, "urlopen", fake_urlopen)
    result = datadog.search_for_finding("SE", "CORORA-R-ERR-NO-SEC-TERM-OVRD", config=cfg)

    assert captured["url"] == "https://api.us5.datadoghq.com/api/v2/logs/events/search"
    assert captured["api_key"] == "dd-api-secret"
    assert captured["app_key"] == "dd-app-secret"
    body = captured["body"]
    assert isinstance(body, dict)
    assert "ERR-NO-SEC-TERM-OVRD" in body["filter"]["query"]
    assert "service:order-edit" in body["filter"]["query"]
    assert body["filter"]["from"] == "now-4h"
    assert result["reachable"] is True
    assert result["log_count"] == 1
    assert result["filtered_out"] == 1
    assert result["logs"][0]["id"] == "live-1"
    assert result["logs"][0]["status_group"] == "error"
    assert "dd-api-secret" not in json.dumps(result)
    assert "dd-app-secret" not in json.dumps(result)
