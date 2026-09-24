"""Tests for Jira Cloud integration (offline: mock mode + patched transport)."""

from __future__ import annotations

import io
import json

import pytest

from cobol_error_scanner import jira_integration as jira
from cobol_error_scanner.jira_integration import JiraConfig, build_jql


def test_build_jql_with_code_and_field():
    jql = build_jql("EV", "ERROR-SHIP-VIA")
    assert 'text ~ "EV"' in jql
    assert 'text ~ "ERROR-SHIP-VIA"' in jql
    assert " OR " in jql
    assert jql.strip().endswith("ORDER BY updated DESC")


def test_build_jql_with_projects_and_extra():
    jql = build_jql("EV", "", projects=["OPS", "PAY"], extra_jql="labels = cobol")
    assert 'project in ("OPS", "PAY")' in jql
    assert "(labels = cobol)" in jql


def test_build_jql_escapes_quotes():
    jql = build_jql('AB"C', "")
    assert '\\"' in jql


def test_build_jql_empty_terms_has_fallback():
    jql = build_jql("", "")
    assert "created >= -365d" in jql


def test_adf_to_text_flattens_nested_nodes():
    adf = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Root cause found."}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "Deployed fix."}]},
        ],
    }
    text = jira._adf_to_text(adf)
    assert "Root cause found." in text
    assert "Deployed fix." in text


def test_analyze_issue_extracts_resolution_excerpt():
    issue = jira._BUILTIN_MOCK_ISSUES[0]
    analyzed = jira.analyze_issue(issue, "https://acme.atlassian.net")
    assert analyzed["key"] == "OPS-4821"
    assert analyzed["url"] == "https://acme.atlassian.net/browse/OPS-4821"
    assert analyzed["is_resolved"] is True
    assert analyzed["resolution"] == "Fixed"
    assert "Root cause" in analyzed["resolution_excerpt"]
    assert analyzed["comment_count"] == 2


def test_search_for_finding_not_configured():
    cfg = JiraConfig()
    result = jira.search_for_finding("EV", "ERROR-SHIP-VIA", config=cfg)
    assert result["configured"] is False
    assert result["reachable"] is False
    assert "JIRA_BASE_URL" in result["error"]
    assert result["issues"] == []


def test_search_for_finding_mock_mode_filters_by_term():
    cfg = JiraConfig(mock="1")
    result = jira.search_for_finding("EV", "ERROR-SHIP-VIA", config=cfg)
    assert result["configured"] is True
    assert result["reachable"] is True
    assert result["issue_count"] >= 1
    keys = {issue["key"] for issue in result["issues"]}
    assert "OPS-4821" in keys
    assert "resolved" in result["summary"].lower()
    assert result["insights"]


def test_search_for_finding_mock_mode_no_match():
    cfg = JiraConfig(mock="1")
    result = jira.search_for_finding("ZZ", "NOTHING-MATCHES-THIS", config=cfg)
    assert result["configured"] is True
    assert result["issue_count"] == 0


def test_config_from_env_reads_values(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", "https://acme.atlassian.net/")
    monkeypatch.setenv("JIRA_EMAIL", "dev@acme.io")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret-token")
    monkeypatch.setenv("JIRA_PROJECTS", "OPS, PAY")
    cfg = JiraConfig.from_env()
    assert cfg.base_url == "https://acme.atlassian.net"  # trailing slash stripped
    assert cfg.is_configured is True
    assert cfg.projects == ["OPS", "PAY"]
    # Public dict must never leak the token.
    public = cfg.public_dict()
    assert "api_token" not in public
    assert "secret-token" not in json.dumps(public)


def test_search_for_finding_live_path_with_patched_transport(monkeypatch):
    """Exercise the real (non-mock) code path with a fake HTTP transport."""
    cfg = JiraConfig(
        base_url="https://acme.atlassian.net",
        email="dev@acme.io",
        api_token="token",
    )

    captured: dict[str, object] = {}

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None, context=None):  # noqa: ANN001
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        body = request.data.decode("utf-8")
        captured["jql"] = json.loads(body)["jql"]
        payload = {
            "issues": [
                {
                    "key": "OPS-9",
                    "fields": {
                        "summary": "EV edit failure",
                        "status": {"name": "Done", "statusCategory": {"key": "done"}},
                        "resolution": {"name": "Fixed"},
                        "comment": {
                            "comments": [
                                {
                                    "author": {"displayName": "QA"},
                                    "created": "2026-01-01T00:00:00.000+0000",
                                    "body": "Resolution: corrected the mapping.",
                                }
                            ]
                        },
                    },
                }
            ]
        }
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(jira.urllib.request, "urlopen", fake_urlopen)

    result = jira.search_for_finding("EV", "ERROR-SHIP-VIA", config=cfg)
    assert result["reachable"] is True
    assert result["issue_count"] == 1
    assert result["issues"][0]["key"] == "OPS-9"
    assert result["issues"][0]["is_resolved"] is True
    assert "corrected the mapping" in result["issues"][0]["resolution_excerpt"]
    # Auth header uses HTTP Basic and the search endpoint is correct.
    assert str(captured["auth"]).startswith("Basic ")
    assert captured["url"].endswith("/rest/api/3/search")
    assert 'text ~ "EV"' in captured["jql"]


def test_search_for_finding_http_error(monkeypatch):
    cfg = JiraConfig(base_url="https://acme.atlassian.net", email="a@b.c", api_token="t")

    def boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise jira.urllib.error.URLError("connection refused")

    monkeypatch.setattr(jira.urllib.request, "urlopen", boom)
    result = jira.search_for_finding("EV", "", config=cfg)
    assert result["reachable"] is False
    assert "Could not reach Jira" in result["error"]
