"""Offline tests for the Datadog Order Create analysis report."""

from __future__ import annotations

import io
import json

from cobol_error_scanner import datadog_analysis as analysis
from cobol_error_scanner import datadog_connection as connection
from cobol_error_scanner.datadog_connection import DatadogConfig


V6_UK_PROD = {
    "attributes": {
        "host": "uschileai1401",
        "service": "OrderCreate_v6_1",
        "tags": ["env:production", "service:ordercreate_v6_1"],
        "message": (
            "<pfx5:CountryCode>UK</pfx5:CountryCode>"
            "<pfx5:LogDescription>OMP Response</pfx5:LogDescription>"
            '{"serviceresponse":{"responsepreamble":{"responsestatus":"FAILED","errorcode":"EV"}}}'
        ),
    }
}

V2_US_PROD = {
    "attributes": {
        "host": "uschileai1404",
        "service": "OrderCreate_v2_0",
        "tags": ["env:production"],
        "message": (
            "<pfx5:CountryCode>US</pfx5:CountryCode>"
            "<pfx5:LogDescription>OrderCreate Response</pfx5:LogDescription>"
            "<requestStatus>FAILED</requestStatus>"
            "<ResponseFlag>E</ResponseFlag><ErrorType>V</ErrorType>"
        ),
    }
}

V2_DE_TEST = {
    "attributes": {
        "host": "uschleai2403",
        "service": "OrderCreate_v2",
        "tags": ["env:tibco_bw6.11_qa_eai"],
        "message": (
            "<pfx5:CountryCode>DE</pfx5:CountryCode>"
            "<pfx5:LogDescription>OrderCreate Response</pfx5:LogDescription>"
            "<returnCode>EV</returnCode>"
        ),
    }
}

SUCCESS_OTHER = {
    "attributes": {
        "host": "uschileai1402",
        "service": "OrderCreate_v6_1",
        "tags": ["env:production"],
        "message": (
            "<pfx5:CountryCode>US</pfx5:CountryCode>"
            "<pfx5:LogDescription>OMP Response</pfx5:LogDescription>"
            '{"responsepreamble":{"responsestatus":"SUCCESS","errorcode":"SG"}}'
        ),
    }
}


def test_region_and_environment_classification():
    assert analysis.classify_region("UK") == "EMEA"
    assert analysis.classify_region("us") == "North America"
    assert analysis.classify_region("IN") == "Other"
    assert analysis.classify_environment("uschileai1402", "") == "Production"
    assert analysis.classify_environment("uschleai2403", "tibco_bw6.11_qa_eai") == "Test"
    assert analysis.service_family("OrderCreate_v6_1") == "OrderCreate_v6*"
    assert analysis.service_family("OrderCreate_v2_0") == "OrderCreate_v2*"


def test_event_matches_error_code_or_failed_response_flag():
    assert analysis.event_matches(V6_UK_PROD["attributes"]["message"], "EV")
    assert analysis.event_matches(V2_US_PROD["attributes"]["message"], "EV")
    assert analysis.event_matches(V2_DE_TEST["attributes"]["message"], "EV")
    assert analysis.event_matches(SUCCESS_OTHER["attributes"]["message"], "EV") is False
    failed_other_flag = (
        "<LogDescription>Response</LogDescription>"
        "<requestStatus>FAILED</requestStatus><ResponseFlag>S</ResponseFlag><ErrorType>G</ErrorType>"
    )
    assert analysis.event_matches(failed_other_flag, "EV") is False


def test_summarize_groups_region_environment_host_and_service():
    report = analysis.summarize_events(
        [V6_UK_PROD, V2_US_PROD, V2_DE_TEST, SUCCESS_OTHER],
        "EV",
    )
    assert report["matched"] == 3
    assert report["summary"] == {
        "production": 2,
        "test": 1,
        "north_america": 1,
        "emea": 2,
        "other": 0,
        "order_create_v6": 1,
        "order_create_v2": 2,
    }
    hosts = {(row["host"], row["service"], row["region"], row["environment"]) for row in report["groups"]}
    assert ("uschileai1401", "OrderCreate_v6*", "EMEA", "Production") in hosts
    assert ("uschileai1404", "OrderCreate_v2*", "North America", "Production") in hosts
    assert ("uschleai2403", "OrderCreate_v2*", "EMEA", "Test") in hosts
    dumped = json.dumps(report)
    assert "CustomerNumber" not in dumped


def test_query_names_services_and_code_without_secrets():
    query = analysis.build_log_query("EV")
    assert "OrderCreate_v6*" in query
    assert "OrderCreate_v2*" in query
    assert "EV" in query
    assert "FAILED" in query


def test_analyze_mock_skips_network():
    report = analysis.analyze_order_create("EV", DatadogConfig(mock="1", site="us5.datadoghq.com"))
    assert report["configured"] is True
    assert report["mock"] is True
    assert report["window_days"] == 15
    assert report["matched"] == 3
    assert report["summary"]["production"] == 2
    assert report["summary"]["test"] == 1
    assert "ddpat" not in json.dumps(report)


def test_analyze_searches_logs_and_hides_token(monkeypatch):
    cfg = DatadogConfig(access_token="ddpat_secret", site="us5.datadoghq.com")
    calls: list[str] = []

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None, context=None):  # noqa: ANN001
        calls.append(request.full_url)
        assert request.get_method() == "POST"
        assert request.get_header("Authorization") == "Bearer ddpat_secret"
        body = json.loads(request.data.decode("utf-8"))
        assert "OrderCreate_v6*" in body["filter"]["query"]
        assert body["filter"]["from"] == "now-15d"
        payload = {"data": [V6_UK_PROD], "meta": {"page": {}}}
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(connection.urllib.request, "urlopen", fake_urlopen)
    report = analysis.analyze_order_create("EV", cfg)
    assert calls == ["https://api.us5.datadoghq.com/api/v2/logs/events/search"]
    assert report["matched"] == 1
    assert report["groups"][0]["region"] == "EMEA"
    assert report["groups"][0]["host"] == "uschileai1401"
    assert "ddpat_secret" not in json.dumps(report)


def test_extract_exchange_pairs_request_and_response_json():
    request = json.dumps({"order": {"shipVia": "XC"}})
    response = json.dumps(
        {"serviceresponse": {"responsepreamble": {"responsestatus": "FAILED", "errorcode": "ER"}}}
    )
    response_only = (
        "<pfx5:CorrelationId>corr-1</pfx5:CorrelationId>"
        "<pfx5:CountryCode>US</pfx5:CountryCode>"
        "<pfx5:LogDescription>OMP Response</pfx5:LogDescription>"
        f"<pfx5:ResponseLogPayload>{response}</pfx5:ResponseLogPayload>"
        '{"serviceresponse":{"responsepreamble":{"responsestatus":"FAILED","errorcode":"ER"}}}'
    )
    request_only = (
        "<pfx5:CorrelationId>corr-1</pfx5:CorrelationId>"
        "<pfx5:LogDescription>OrderCreate Request</pfx5:LogDescription>"
        f"<pfx5:RequestLogPayload>{request}</pfx5:RequestLogPayload>"
    )
    events = [
        {
            "attributes": {
                "host": "uschileai1401",
                "service": "OrderCreate_v6_1",
                "tags": ["env:production"],
                "timestamp": "2026-09-28T22:05:39Z",
                "message": response_only,
            }
        },
        {
            "attributes": {
                "host": "uschileai1401",
                "service": "OrderCreate_v6_1",
                "tags": ["env:production"],
                "message": request_only,
            }
        },
    ]
    rows = analysis.build_exchanges(events, "ER")
    assert len(rows) == 1
    assert rows[0]["service"] == "OrderCreate_v6*"
    assert rows[0]["correlation_id"] == "corr-1"
    assert rows[0]["request"] == {"order": {"shipVia": "XC"}}
    assert rows[0]["response"]["serviceresponse"]["responsepreamble"]["errorcode"] == "ER"


def test_failure_exchanges_mock_redacts_token_and_keeps_order_fields():
    report = analysis.failure_exchanges("EV", DatadogConfig(mock="1", site="us5.datadoghq.com"))
    assert report["connected"] is True
    assert len(report["exchanges"]) == 1
    exchange = report["exchanges"][0]
    assert exchange["service"] == "OrderCreate_v6*"
    assert exchange["request"]["serviceRequest"]["order"]["orderType"] == "STOCK"
    dumped = json.dumps(report)
    assert "should-not-leak" not in dumped
    assert "[redacted]" in dumped


def test_failure_exchanges_keeps_only_the_selected_host_and_service():
    matched = analysis.failure_exchanges(
        "EV",
        DatadogConfig(mock="1"),
        host="uschileai1401",
        service="OrderCreate_v6*",
    )
    assert len(matched["exchanges"]) == 1
    assert matched["exchanges"][0]["host"] == "uschileai1401"
    other = analysis.failure_exchanges(
        "EV",
        DatadogConfig(mock="1"),
        host="uschileai1402",
        service="OrderCreate_v2*",
    )
    assert other["exchanges"] == []


def test_failure_exchanges_checks_connection_before_search(monkeypatch):
    calls: list[str] = []

    def fake_connect(config):  # noqa: ANN001
        calls.append("connect")
        return {"connected": False, "error": "Datadog accepted the access token, but it cannot read logs."}

    def fake_search(*args, **kwargs):  # noqa: ANN002
        calls.append("search")
        return [], False

    monkeypatch.setattr(analysis, "connect", fake_connect)
    monkeypatch.setattr(analysis, "_search_events", fake_search)
    report = analysis.failure_exchanges(
        "ER",
        DatadogConfig(access_token="ddpat_secret", site="us5.datadoghq.com"),
    )
    assert calls == ["connect"]
    assert report["connected"] is False
    assert report["exchanges"] == []
    assert "cannot read logs" in report["error"]
    assert "ddpat_secret" not in json.dumps(report)
