"""Datadog log search for the operational-docs workflow.

Given a COBOL finding's error code / error field, this module searches Datadog
logs for events that mention the same terms analysts already use for Jira, then
returns a short roll-up (error vs warning counts and the matching messages).

Configuration comes exclusively from environment variables so API keys are
never committed:

    DATADOG_API_KEY       Datadog API key
    DATADOG_APP_KEY       Datadog application key (required for log search)
    DATADOG_SITE          optional site, default datadoghq.com
                          (us3.datadoghq.com, us5.datadoghq.com, datadoghq.eu, …)
    DATADOG_EXTRA_QUERY   optional log query AND-ed onto the generated search
    DATADOG_INDEXES       optional comma-separated log indexes
    DATADOG_LOOKBACK      optional window such as 15m, 4h, or 7d (default 7d)
    DATADOG_MAX_RESULTS   optional, default 10, capped at 50
    DATADOG_TIMEOUT       optional request timeout seconds, default 15
    DATADOG_VERIFY_SSL    optional, "0" to disable TLS verification
    DATADOG_MOCK          optional, "1"/"builtin" for sample logs, or a path
                          to a JSON file of log events

Datadog authenticates with the DD-API-KEY and DD-APPLICATION-KEY headers.
Log search uses POST /api/v2/logs/events/search.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from cobol_error_scanner.jira_integration import derive_search_terms

_SEARCH_PATH = "/api/v2/logs/events/search"
_LOOKBACK_RE = re.compile(r"^(\d+)([mhd])$")
_MAX_MESSAGE_LEN = 600

# site token -> (api origin, app origin)
_SITES: dict[str, tuple[str, str]] = {
    "datadoghq.com": ("https://api.datadoghq.com", "https://app.datadoghq.com"),
    "us3.datadoghq.com": ("https://api.us3.datadoghq.com", "https://app.us3.datadoghq.com"),
    "us5.datadoghq.com": ("https://api.us5.datadoghq.com", "https://app.us5.datadoghq.com"),
    "datadoghq.eu": ("https://api.datadoghq.eu", "https://app.datadoghq.eu"),
    "ap1.datadoghq.com": ("https://api.ap1.datadoghq.com", "https://app.ap1.datadoghq.com"),
    "ap2.datadoghq.com": ("https://api.ap2.datadoghq.com", "https://app.ap2.datadoghq.com"),
    "uk1.datadoghq.com": ("https://api.uk1.datadoghq.com", "https://app.uk1.datadoghq.com"),
    "ddog-gov.com": ("https://api.ddog-gov.com", "https://app.ddog-gov.com"),
    "us2.ddog-gov.com": ("https://api.us2.ddog-gov.com", "https://app.us2.ddog-gov.com"),
}

_ERROR_STATUSES = {"error", "critical", "alert", "emergency"}
_WARN_STATUSES = {"warn", "warning"}


class DatadogError(Exception):
    """Raised when a Datadog request fails."""


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


def site_origins(site: str) -> tuple[str, str]:
    token = normalize_site(site)
    if token in _SITES:
        return _SITES[token]
    return (f"https://api.{token}", f"https://app.{token}")


@dataclass
class DatadogConfig:
    api_key: str = ""
    app_key: str = ""
    site: str = "datadoghq.com"
    extra_query: str = ""
    indexes: list[str] = field(default_factory=list)
    lookback: str = "7d"
    max_results: int = 10
    timeout: float = 15.0
    verify_ssl: bool = True
    mock: str = ""

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "DatadogConfig":
        src = env if env is not None else os.environ
        indexes = [
            item.strip()
            for item in str(src.get("DATADOG_INDEXES", "")).split(",")
            if item.strip()
        ]
        try:
            max_results = int(str(src.get("DATADOG_MAX_RESULTS", "10")).strip() or "10")
        except ValueError:
            max_results = 10
        try:
            timeout = float(str(src.get("DATADOG_TIMEOUT", "15")).strip() or "15")
        except ValueError:
            timeout = 15.0
        lookback = str(src.get("DATADOG_LOOKBACK", "7d")).strip() or "7d"
        if not _LOOKBACK_RE.match(lookback):
            lookback = "7d"
        verify_ssl = str(src.get("DATADOG_VERIFY_SSL", "1")).strip() not in {"0", "false", "False"}
        return cls(
            api_key=str(src.get("DATADOG_API_KEY", "")).strip(),
            app_key=str(src.get("DATADOG_APP_KEY", "")).strip(),
            site=normalize_site(str(src.get("DATADOG_SITE", "datadoghq.com"))),
            extra_query=str(src.get("DATADOG_EXTRA_QUERY", "")).strip(),
            indexes=indexes,
            lookback=lookback,
            max_results=max(1, min(max_results, 50)),
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
        return site_origins(self.site)[0]

    @property
    def app_base(self) -> str:
        return site_origins(self.site)[1]

    def public_dict(self) -> dict[str, Any]:
        """Non-secret config summary safe to return to the browser."""
        return {
            "configured": self.is_configured,
            "site": self.site,
            "api_host": self.api_base,
            "app_host": self.app_base,
            "lookback": self.lookback,
            "mock": self.is_mock,
        }


def _escape_query(term: str) -> str:
    return term.replace("\\", "\\\\").replace('"', '\\"')


def build_log_query(terms: list[str], extra_query: str = "") -> str:
    """Build a Datadog log query that phrase-matches the finding terms."""
    clean = [t.strip() for t in terms if t and t.strip()]
    if clean:
        clause = " OR ".join(f'"{_escape_query(term)}"' for term in clean)
        query = f"({clause})"
    else:
        query = "*"
    extra = extra_query.strip()
    if extra:
        return f"{query} {extra}"
    return query


def _ssl_context(config: DatadogConfig) -> ssl.SSLContext | None:
    if config.verify_ssl:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _post_json(config: DatadogConfig, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = config.api_base.rstrip("/") + "/" + path.lstrip("/")
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("DD-API-KEY", config.api_key)
    request.add_header("DD-APPLICATION-KEY", config.app_key)
    request.add_header("Content-Type", "application/json")
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
        raise DatadogError(
            f"Datadog returned HTTP {exc.code} for {path}. {detail}".strip()
        ) from exc
    except urllib.error.URLError as exc:
        raise DatadogError(f"Could not reach Datadog at {config.api_base}: {exc.reason}") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise DatadogError("Datadog returned a non-JSON response.") from exc
    if not isinstance(parsed, dict):
        raise DatadogError("Datadog returned an unexpected response.")
    return parsed


def _terms_in_text(text: str, terms: list[str]) -> list[str]:
    if not text or not terms:
        return []
    lowered = text.lower()
    return [term for term in terms if term and term.lower() in lowered]


def _mention_snippet(text: str, terms: list[str]) -> str:
    if not text:
        return ""
    lowered = text.lower()
    first = -1
    for term in terms:
        if not term:
            continue
        idx = lowered.find(term.lower())
        if idx != -1 and (first == -1 or idx < first):
            first = idx
    if first == -1:
        snippet = text.strip()
    else:
        start = max(0, first - 140)
        end = min(len(text), first + 180)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "… " + snippet
        if end < len(text):
            snippet = snippet + " …"
    return snippet[:_MAX_MESSAGE_LEN]


def _event_blob(attributes: dict[str, Any]) -> str:
    nested = attributes.get("attributes")
    nested_text = json.dumps(nested, ensure_ascii=False) if isinstance(nested, dict) else ""
    tags = " ".join(str(tag) for tag in (attributes.get("tags") or []) if tag)
    return " ".join(
        part
        for part in (
            str(attributes.get("message") or ""),
            str(attributes.get("service") or ""),
            str(attributes.get("host") or ""),
            tags,
            nested_text,
        )
        if part
    )


def _status_group(status: str) -> str:
    token = status.strip().lower()
    if token in _ERROR_STATUSES:
        return "error"
    if token in _WARN_STATUSES:
        return "warn"
    return "info"


def analyze_log(
    event: dict[str, Any],
    *,
    app_base: str,
    query: str,
    search_terms: list[str],
) -> dict[str, Any]:
    attributes = event.get("attributes") if isinstance(event.get("attributes"), dict) else {}
    message = str(attributes.get("message") or "")
    status = str(attributes.get("status") or "")
    tags = [str(tag) for tag in (attributes.get("tags") or []) if tag]
    blob = _event_blob(attributes)
    matched = _terms_in_text(blob, search_terms)
    log_id = str(event.get("id") or "")
    logs_url = ""
    if app_base:
        logs_url = f"{app_base.rstrip('/')}/logs?query={urllib.parse.quote(query)}"
    return {
        "id": log_id,
        "url": logs_url,
        "message": _mention_snippet(message, search_terms),
        "status": status,
        "status_group": _status_group(status),
        "service": str(attributes.get("service") or ""),
        "host": str(attributes.get("host") or ""),
        "timestamp": str(attributes.get("timestamp") or ""),
        "tags": tags,
        "matched_terms": matched,
    }


def _summarize(logs: list[dict[str, Any]], terms: list[str]) -> tuple[str, list[str]]:
    label = " / ".join(term for term in terms if term) or "the finding"
    if not logs:
        return (f"No Datadog logs mention {label}.", [])
    errors = [item for item in logs if item["status_group"] == "error"]
    warnings = [item for item in logs if item["status_group"] == "warn"]
    summary = (
        f"Found {len(logs)} Datadog log event(s) mentioning {label}; "
        f"{len(errors)} error, {len(warnings)} warning."
    )
    insights: list[str] = []
    for item in logs[:3]:
        service = item["service"] or "unknown service"
        status = item["status"] or item["status_group"]
        insights.append(f"{service} ({status}): {item['message']}"[:_MAX_MESSAGE_LEN])
    return summary, insights


_BUILTIN_MOCK_EVENTS: list[dict[str, Any]] = [
    {
        "id": "log-se-1001",
        "type": "log",
        "attributes": {
            "service": "order-edit",
            "host": "mainframe-bridge-01",
            "status": "error",
            "timestamp": "2026-03-18T14:22:11Z",
            "message": (
                "ORP676 SE edit failed: SET CORORA-R-ERR-NO-SEC-TERM-OVRD. "
                "Account is missing a secondary-term override."
            ),
            "tags": ["env:prod", "error_code:SE"],
        },
    },
    {
        "id": "log-se-1002",
        "type": "log",
        "attributes": {
            "service": "order-edit",
            "host": "mainframe-bridge-01",
            "status": "warn",
            "timestamp": "2026-03-18T14:21:02Z",
            "message": "Retrying SE edit after ERR-NO-SEC-TERM-OVRD on order P28064110.",
            "tags": ["env:prod"],
        },
    },
    {
        "id": "log-ev-2001",
        "type": "log",
        "attributes": {
            "service": "shipment-edit",
            "host": "mainframe-bridge-02",
            "status": "error",
            "timestamp": "2026-02-02T08:11:00Z",
            "message": "ERROR-SHIP-VIA rejected a lowercase carrier code on order P28062375.",
            "tags": ["env:prod", "error_code:EV"],
        },
    },
]


def _load_mock_events(config: DatadogConfig) -> list[dict[str, Any]]:
    token = config.mock.strip()
    if token in {"1", "builtin", "true", "True", ""}:
        return list(_BUILTIN_MOCK_EVENTS)
    path = os.path.expanduser(token)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"]
        if isinstance(data, list):
            return data
    return list(_BUILTIN_MOCK_EVENTS)


def _mock_matches(event: dict[str, Any], terms: list[str]) -> bool:
    lowered = [term.strip().lower() for term in terms if term and term.strip()]
    if not lowered:
        return True
    attributes = event.get("attributes") if isinstance(event.get("attributes"), dict) else {}
    hay = _event_blob(attributes).lower()
    return any(term in hay for term in lowered)


def search_for_finding(
    error_code: str,
    error_field: str,
    *,
    config: DatadogConfig | None = None,
) -> dict[str, Any]:
    """Search Datadog logs related to a finding and summarize matching events."""
    cfg = config or DatadogConfig.from_env()
    terms = derive_search_terms(error_code, error_field)
    query = build_log_query(terms, cfg.extra_query)
    payload: dict[str, Any] = {
        "configured": cfg.is_configured,
        "mock": cfg.is_mock,
        "site": cfg.site,
        "api_host": cfg.api_base,
        "app_host": cfg.app_base,
        "query": {
            "error_code": error_code,
            "error_field": error_field,
            "terms": terms,
            "log_query": query,
            "lookback": cfg.lookback,
        },
        "logs": [],
        "log_count": 0,
        "total_matched": 0,
        "filtered_out": 0,
        "summary": "",
        "insights": [],
    }

    if not cfg.is_configured:
        payload["reachable"] = False
        payload["error"] = (
            "Datadog is not configured. Set DATADOG_API_KEY and DATADOG_APP_KEY "
            "(see README) to search logs for this finding."
        )
        return payload

    body: dict[str, Any] = {
        "filter": {
            "query": query,
            "from": f"now-{cfg.lookback}",
            "to": "now",
        },
        "sort": "-timestamp",
        "page": {"limit": cfg.max_results},
    }
    if cfg.indexes:
        body["filter"]["indexes"] = cfg.indexes

    try:
        if cfg.is_mock:
            raw_events = [
                event for event in _load_mock_events(cfg) if _mock_matches(event, terms)
            ][: cfg.max_results]
        else:
            response = _post_json(cfg, _SEARCH_PATH, body)
            raw_events = response.get("data") or []
            if not isinstance(raw_events, list):
                raw_events = []
    except DatadogError as exc:
        payload["reachable"] = False
        payload["error"] = str(exc)
        return payload

    analyzed = [
        analyze_log(event, app_base=cfg.app_base, query=query, search_terms=terms)
        for event in raw_events
        if isinstance(event, dict)
    ]
    total_matched = len(analyzed)
    logs = [item for item in analyzed if item["matched_terms"]] if terms else analyzed
    filtered_out = total_matched - len(logs)
    summary, insights = _summarize(logs, terms)
    payload.update(
        {
            "reachable": True,
            "logs": logs,
            "log_count": len(logs),
            "total_matched": total_matched,
            "filtered_out": filtered_out,
            "summary": summary,
            "insights": insights,
        }
    )
    return payload
