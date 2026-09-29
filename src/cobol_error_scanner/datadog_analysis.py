"""Order Create response report from Datadog logs.

Looks at OrderCreate v6 and v2 response logs for the last 15 days. A log is
included when its error code matches the finding, or when the request status
is FAILED and the response flag matches that code. Results are grouped by
North America / EMEA / Other, by production vs test, and by host and service.
"""

from __future__ import annotations

import html
import http.client
import re
import time
from collections import Counter
from typing import Any

from cobol_error_scanner.datadog_connection import (
    DatadogConfig,
    DatadogConnectionError,
    DatadogHTTPError,
    _request_json,
    _scrub,
)

WINDOW_DAYS = 15
_PAGE_LIMIT = 100
_MAX_PAGES = 5
_SEARCH_PATH = "/api/v2/logs/events/search"
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$")
_PROD_HOSTS = {f"uschileai140{n}" for n in range(1, 5)}

_NORTH_AMERICA = frozenset({"US", "CA", "MX", "PR", "VI", "GU", "AS", "UM", "BM"})
_EMEA = frozenset(
    {
        "UK",
        "GB",
        "IE",
        "FR",
        "DE",
        "ES",
        "IT",
        "NL",
        "BE",
        "LU",
        "PT",
        "AT",
        "CH",
        "SE",
        "NO",
        "DK",
        "FI",
        "IS",
        "PL",
        "CZ",
        "SK",
        "HU",
        "RO",
        "BG",
        "GR",
        "HR",
        "SI",
        "EE",
        "LV",
        "LT",
        "CY",
        "MT",
        "UA",
        "RS",
        "BA",
        "MK",
        "AL",
        "MD",
        "BY",
        "AE",
        "SA",
        "QA",
        "KW",
        "BH",
        "OM",
        "IL",
        "JO",
        "LB",
        "TR",
        "EG",
        "IQ",
        "YE",
        "ZA",
        "NG",
        "KE",
        "MA",
        "TN",
        "DZ",
        "GH",
        "EH",
        "CI",
        "SN",
        "TZ",
        "UG",
        "ET",
        "AO",
        "MZ",
        "NA",
        "BW",
        "MU",
        "RE",
    }
)

_REGION_ORDER = ("North America", "EMEA", "Other")
_ENV_ORDER = ("Production", "Test", "Unknown")


def classify_region(country: str) -> str:
    code = (country or "").strip().upper()
    if code in _NORTH_AMERICA:
        return "North America"
    if code in _EMEA:
        return "EMEA"
    return "Other"


def classify_environment(host: str, env_tag: str) -> str:
    host_l = (host or "").strip().lower()
    env_l = (env_tag or "").strip().lower()
    if host_l in _PROD_HOSTS or env_l == "production":
        return "Production"
    if any(token in env_l for token in ("qa", "test", "dev", "stage", "uat")):
        return "Test"
    if host_l:
        return "Test"
    return "Unknown"


def service_family(service: str) -> str:
    low = (service or "").lower()
    compact = re.sub(r"[^a-z0-9]", "", low)
    if "ordercreatev6" in compact:
        return "OrderCreate_v6*"
    if "ordercreatev2" in compact:
        return "OrderCreate_v2*"
    return "Other"


def build_log_query(error_code: str) -> str:
    """Datadog log query for Order Create responses of one error code."""
    code = error_code.strip()
    parts = [
        f'"<ErrorCode>{code}"',
        f'"<returnCode>{code}"',
        f'"<lineErrorCode>{code}"',
        f'"\\"errorcode\\":\\"{code}\\""',
        f'"<ResponseFlag>{code}"',
    ]
    if len(code) == 2 and code.isalnum():
        parts.append(f'("<ResponseFlag>{code[0]}" "<ErrorType>{code[1]}")')
    failed = (
        '("<requestStatus>FAILED" OR "<HeaderResponse>Failed" OR '
        f'"\\"responsestatus\\":\\"FAILED\\"") ({" OR ".join(parts)})'
    )
    code_match = " OR ".join(parts)
    return (
        "service:(OrderCreate_v6* OR OrderCreate_v2*) Response "
        f"({code_match} OR {failed})"
    )


def _xml_values(text: str, name: str) -> list[str]:
    return [
        " ".join(value.split())
        for value in re.findall(
            rf"<(?:\w+:)?{name}>([^<]*)</(?:\w+:)?{name}>",
            text,
            flags=re.IGNORECASE,
        )
    ]


def _json_values(text: str, name: str) -> list[str]:
    return [
        " ".join(value.split())
        for value in re.findall(rf'"{name}"\s*:\s*"([^"]*)"', text, flags=re.IGNORECASE)
    ]


def _upper_set(values: list[str]) -> set[str]:
    return {value.strip().upper() for value in values if value and value.strip()}


def event_matches(message: str, error_code: str) -> bool:
    """True when the log is an Order Create response for this error code."""
    text = html.unescape(html.unescape(message or ""))
    if "response" not in text.lower():
        return False
    code = error_code.strip().upper()
    error_codes = _upper_set(
        _xml_values(text, "ErrorCode")
        + _xml_values(text, "returnCode")
        + _xml_values(text, "lineErrorCode")
        + _json_values(text, "errorcode")
    )
    flags = _upper_set(_xml_values(text, "ResponseFlag"))
    flag_chars = [value.strip() for value in _xml_values(text, "ResponseFlag")]
    type_chars = [value.strip() for value in _xml_values(text, "ErrorType")]
    for flag, error_type in zip(flag_chars, type_chars):
        if len(flag) == 1 and len(error_type) == 1:
            flags.add((flag + error_type).upper())
    statuses = _upper_set(
        _xml_values(text, "requestStatus")
        + _xml_values(text, "HeaderResponse")
        + _json_values(text, "responsestatus")
        + _json_values(text, "requeststatus")
    )
    failed = bool(statuses & {"FAILED", "FAIL"})
    if code in error_codes:
        return True
    return failed and code in flags


def _env_tag(tags: list[str] | None) -> str:
    for tag in tags or []:
        if isinstance(tag, str) and tag.lower().startswith("env:"):
            return tag.split(":", 1)[1]
    return ""


def _event_facts(event: dict[str, Any]) -> dict[str, str]:
    attributes = event.get("attributes") or {}
    message = str(attributes.get("message") or "")
    text = html.unescape(html.unescape(message))
    countries = [value for value in _xml_values(text, "CountryCode") if value]
    servers = [value for value in _xml_values(text, "ServerName") if value]
    services = [value for value in _xml_values(text, "ServiceName") if value]
    host = str(attributes.get("host") or (servers[0] if servers else "")).strip()
    service = str(attributes.get("service") or (services[0] if services else "")).strip()
    return {
        "host": host or "unknown",
        "service": service,
        "env": _env_tag(attributes.get("tags") if isinstance(attributes.get("tags"), list) else []),
        "country": (countries[0] if countries else "").upper(),
        "message": message,
    }


def summarize_events(events: list[dict[str, Any]], error_code: str) -> dict[str, Any]:
    """Group matching logs. Raw messages are not returned."""
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    matched = 0
    for event in events:
        facts = _event_facts(event)
        if not event_matches(facts["message"], error_code):
            continue
        matched += 1
        region = classify_region(facts["country"])
        environment = classify_environment(facts["host"], facts["env"])
        family = service_family(facts["service"])
        key = (region, environment, facts["host"], family)
        bucket = groups.get(key)
        if bucket is None:
            bucket = {
                "region": region,
                "environment": environment,
                "host": facts["host"],
                "service": family,
                "services": Counter(),
                "countries": Counter(),
                "count": 0,
            }
            groups[key] = bucket
        bucket["count"] += 1
        if facts["service"]:
            bucket["services"][facts["service"]] += 1
        if facts["country"]:
            bucket["countries"][facts["country"]] += 1

    rows = []
    for key in sorted(
        groups,
        key=lambda item: (
            _REGION_ORDER.index(item[0]) if item[0] in _REGION_ORDER else 9,
            _ENV_ORDER.index(item[1]) if item[1] in _ENV_ORDER else 9,
            item[2],
            item[3],
        ),
    ):
        bucket = groups[key]
        rows.append(
            {
                "region": bucket["region"],
                "environment": bucket["environment"],
                "host": bucket["host"],
                "service": bucket["service"],
                "services": [
                    {"name": name, "count": count}
                    for name, count in bucket["services"].most_common()
                ],
                "countries": [
                    {"code": code, "count": count}
                    for code, count in bucket["countries"].most_common()
                ],
                "count": bucket["count"],
            }
        )

    def _sum(predicate) -> int:
        return sum(row["count"] for row in rows if predicate(row))

    return {
        "matched": matched,
        "summary": {
            "production": _sum(lambda row: row["environment"] == "Production"),
            "test": _sum(lambda row: row["environment"] == "Test"),
            "north_america": _sum(lambda row: row["region"] == "North America"),
            "emea": _sum(lambda row: row["region"] == "EMEA"),
            "other": _sum(lambda row: row["region"] == "Other"),
            "order_create_v6": _sum(lambda row: row["service"] == "OrderCreate_v6*"),
            "order_create_v2": _sum(lambda row: row["service"] == "OrderCreate_v2*"),
        },
        "groups": rows,
    }


def _search_events(config: DatadogConfig, query: str, days: int) -> tuple[list[dict[str, Any]], bool]:
    events: list[dict[str, Any]] = []
    cursor = None
    truncated = False
    for page_index in range(_MAX_PAGES):
        page: dict[str, Any] = {"limit": _PAGE_LIMIT}
        if cursor:
            page["cursor"] = cursor
        payload = {
            "filter": {"query": query, "from": f"now-{days}d", "to": "now"},
            "sort": "timestamp",
            "page": page,
        }
        body = _search_with_retry(config, payload)
        batch = body.get("data") or []
        if not isinstance(batch, list):
            break
        events.extend(item for item in batch if isinstance(item, dict))
        cursor = str(((body.get("meta") or {}).get("page") or {}).get("after") or "")
        if not cursor or len(batch) < _PAGE_LIMIT:
            return events, False
        if page_index == _MAX_PAGES - 1:
            truncated = True
    return events, truncated


def _search_with_retry(config: DatadogConfig, payload: dict[str, Any]) -> dict[str, Any]:
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            return _request_json(config, _SEARCH_PATH, payload, timeout=max(config.timeout, 60))
        except DatadogHTTPError as exc:
            last_error = exc
            if exc.status != 429 or attempt == 3:
                raise
        except (http.client.IncompleteRead, TimeoutError, ConnectionError, DatadogConnectionError) as exc:
            last_error = exc
            if attempt == 3:
                if isinstance(exc, DatadogConnectionError):
                    raise
                raise DatadogConnectionError("Datadog log search was interrupted before the page finished.") from exc
        time.sleep(delay)
        delay *= 2
    assert last_error is not None
    raise last_error


def _mock_events() -> list[dict[str, Any]]:
    samples = [
        (
            "uschileai1401",
            "OrderCreate_v6_1",
            "production",
            "<pfx5:CountryCode>UK</pfx5:CountryCode><pfx5:LogDescription>OMP Response</pfx5:LogDescription>"
            '{"serviceresponse":{"responsepreamble":{"responsestatus":"FAILED","errorcode":"EV"}}}',
        ),
        (
            "uschileai1402",
            "OrderCreate_v2_0",
            "production",
            "<pfx5:CountryCode>US</pfx5:CountryCode><pfx5:LogDescription>OrderCreate Response</pfx5:LogDescription>"
            "<requestStatus>FAILED</requestStatus><ResponseFlag>E</ResponseFlag><ErrorType>V</ErrorType>",
        ),
        (
            "uschleai2403",
            "OrderCreate_v2",
            "tibco_bw6.11_qa_eai",
            "<pfx5:CountryCode>DE</pfx5:CountryCode><pfx5:LogDescription>OrderCreate Response</pfx5:LogDescription>"
            "<returnCode>EV</returnCode>",
        ),
    ]
    events = []
    for host, service, env, message in samples:
        events.append(
            {
                "attributes": {
                    "host": host,
                    "service": service,
                    "tags": [f"env:{env}", f"service:{service.lower()}"],
                    "message": message,
                }
            }
        )
    return events


def analyze_order_create(
    error_code: str,
    config: DatadogConfig | None = None,
    days: int = WINDOW_DAYS,
) -> dict[str, Any]:
    """Run the 15-day Order Create v2/v6 response report for one error code."""
    cfg = config or DatadogConfig.from_env()
    code = (error_code or "").strip()
    report: dict[str, Any] = {
        **cfg.public_dict(),
        "error_code": code,
        "window_days": days,
        "services": ["OrderCreate_v6*", "OrderCreate_v2*"],
        "production_hosts": ["uschileai1401", "uschileai1402", "uschileai1403", "uschileai1404"],
        "matched": 0,
        "scanned": 0,
        "truncated": False,
        "summary": {
            "production": 0,
            "test": 0,
            "north_america": 0,
            "emea": 0,
            "other": 0,
            "order_create_v6": 0,
            "order_create_v2": 0,
        },
        "groups": [],
    }
    if not cfg.is_configured:
        report["error"] = (
            "Datadog is not configured. Set DD_ACCESS_TOKEN, or "
            "DATADOG_API_KEY and DATADOG_APP_KEY."
        )
        return report
    if not code:
        report["error"] = "This finding has no error code to search for."
        return report
    if not _CODE_RE.fullmatch(code):
        report["error"] = "This error code cannot be used in a Datadog log query."
        return report

    if cfg.is_mock:
        events = _mock_events()
        # Mock samples are for EV. Other codes exercise the same grouping with no rows.
        summary = summarize_events(events, code)
        report.update(summary)
        report["scanned"] = len(events)
        return report

    query = build_log_query(code)
    try:
        events, truncated = _search_events(cfg, query, days)
    except DatadogConnectionError as exc:
        report["error"] = _scrub(cfg, str(exc))
        return report
    summary = summarize_events(events, code)
    report.update(summary)
    report["scanned"] = len(events)
    report["truncated"] = truncated
    return report
