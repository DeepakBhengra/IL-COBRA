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
