"""Jira Cloud connectivity for the operational-docs workflow.

Given a COBOL finding's error code / error field, this module searches a Jira
Cloud instance for related tickets and produces a heuristic "resolution
insight" (status, resolution field, and the most relevant resolution-oriented
comment) so analysts can see how similar issues were handled.

Configuration comes exclusively from environment variables so that secrets
(the Jira API token) are never committed to the repository:

    JIRA_BASE_URL   e.g. https://your-org.atlassian.net
    JIRA_EMAIL      the Atlassian account email used with the API token
    JIRA_API_TOKEN  an Atlassian API token (https://id.atlassian.com)
    JIRA_PROJECTS   optional, comma-separated project keys to scope the search
    JIRA_EXTRA_JQL  optional, extra JQL AND-ed onto the generated query
    JIRA_MAX_RESULTS optional, default 10
    JIRA_TIMEOUT    optional, request timeout seconds, default 15
    JIRA_VERIFY_SSL optional, "0" to disable TLS verification (not recommended)
    JIRA_MOCK       optional, "1"/"builtin" for built-in sample data or a path
                    to a JSON file of issues (for local development/testing)

Jira Cloud uses HTTP Basic auth with the account email as the username and the
API token as the password.
"""

from __future__ import annotations

import base64
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urljoin

# Atlassian removed the legacy POST /rest/api/3/search endpoint (CHANGE-2046);
# the enhanced JQL search endpoint is used instead. Overridable for Jira
# Server/Data Center (which still use /rest/api/2/search) via JIRA_SEARCH_PATH.
_SEARCH_PATH = "/rest/api/3/search/jql"
_DEFAULT_FIELDS = [
    "summary",
    "status",
    "resolution",
    "resolutiondate",
    "updated",
    "created",
    "assignee",
    "priority",
    "labels",
    "issuetype",
    "comment",
]

# Comment/resolution language that signals a documented fix worth surfacing.
_RESOLUTION_KEYWORDS = (
    "root cause",
    "resolution",
    "resolved",
    "resolve",
    "fixed",
    "fix ",
    "workaround",
    "work around",
    "patched",
    "deployed",
    "corrected",
    "mitigat",
    "solution",
)

_MAX_EXCERPT_LEN = 600
# Windowed excerpt around a search-term occurrence, for "where mentioned".
_MENTION_RADIUS = 140
_MAX_MENTION_LEN = 320


@dataclass
class JiraConfig:
    base_url: str = ""
    email: str = ""
    api_token: str = ""
    projects: list[str] = field(default_factory=list)
    extra_jql: str = ""
    max_results: int = 10
    timeout: float = 15.0
    verify_ssl: bool = True
    mock: str = ""
    search_path: str = _SEARCH_PATH

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "JiraConfig":
        src = env if env is not None else os.environ
        projects = [
            p.strip()
            for p in str(src.get("JIRA_PROJECTS", "")).split(",")
            if p.strip()
        ]
        try:
            max_results = int(str(src.get("JIRA_MAX_RESULTS", "10")).strip() or "10")
        except ValueError:
            max_results = 10
        try:
            timeout = float(str(src.get("JIRA_TIMEOUT", "15")).strip() or "15")
        except ValueError:
            timeout = 15.0
        verify_ssl = str(src.get("JIRA_VERIFY_SSL", "1")).strip() not in {"0", "false", "False"}
        return cls(
            base_url=str(src.get("JIRA_BASE_URL", "")).strip().rstrip("/"),
            email=str(src.get("JIRA_EMAIL", "")).strip(),
            api_token=str(src.get("JIRA_API_TOKEN", "")).strip(),
            projects=projects,
            extra_jql=str(src.get("JIRA_EXTRA_JQL", "")).strip(),
            max_results=max(1, min(max_results, 50)),
            timeout=timeout,
            verify_ssl=verify_ssl,
            mock=str(src.get("JIRA_MOCK", "")).strip(),
            search_path=str(src.get("JIRA_SEARCH_PATH", "")).strip() or _SEARCH_PATH,
        )

    @property
    def is_mock(self) -> bool:
        return bool(self.mock)

    @property
    def is_configured(self) -> bool:
        if self.is_mock:
            return True
        return bool(self.base_url and self.email and self.api_token)

    def public_dict(self) -> dict[str, Any]:
        """Non-secret config summary safe to return to the browser."""
        return {
            "configured": self.is_configured,
            "base_url": self.base_url,
            "email": self.email,
            "projects": self.projects,
            "mock": self.is_mock,
        }


class JiraError(Exception):
    """Raised when a Jira request fails."""


def _auth_header(config: JiraConfig) -> str:
    raw = f"{config.email}:{config.api_token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _ssl_context(config: JiraConfig) -> ssl.SSLContext | None:
    if config.verify_ssl:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _post_json(config: JiraConfig, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = urljoin(config.base_url + "/", path.lstrip("/"))
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Authorization", _auth_header(config))
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
        raise JiraError(
            f"Jira returned HTTP {exc.code} for {path}. {detail}".strip()
        ) from exc
    except urllib.error.URLError as exc:
        raise JiraError(f"Could not reach Jira at {config.base_url}: {exc.reason}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise JiraError("Jira returned a non-JSON response.") from exc


def _get_json(config: JiraConfig, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    url = urljoin(config.base_url + "/", path.lstrip("/"))
    if params:
        url = f"{url}?{urlencode(params)}"
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", _auth_header(config))
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
        raise JiraError(f"Jira returned HTTP {exc.code} for {path}. {detail}".strip()) from exc
    except urllib.error.URLError as exc:
        raise JiraError(f"Could not reach Jira at {config.base_url}: {exc.reason}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise JiraError("Jira returned a non-JSON response.") from exc


def _fetch_comment_container(config: JiraConfig, key: str) -> dict[str, Any] | None:
    """Fetch an issue's comment field when the search response omits it.

    The enhanced JQL search endpoint does not always return comment bodies
    inline, so we fall back to the issue endpoint. Failures are non-fatal.
    """
    if not key:
        return None
    try:
        data = _get_json(config, f"/rest/api/3/issue/{key}", {"fields": "comment"})
    except JiraError:
        return None
    fields = data.get("fields") if isinstance(data, dict) else None
    if isinstance(fields, dict) and isinstance(fields.get("comment"), dict):
        return fields["comment"]
    return None


def _escape_jql(term: str) -> str:
    return term.replace("\\", "\\\\").replace('"', '\\"')


# Mapping-catalog prefix on error fields, e.g. "CORORA-R-" / "CORORL-R-".
_MAPPING_PREFIX_RE = re.compile(r"^COROR[A-Z]+-[A-Z0-9]+-", re.IGNORECASE)
# Generic error prefix on the remaining core, e.g. "ERR-" / "ERROR-".
_ERROR_PREFIX_RE = re.compile(r"^(ERROR|ERR)-", re.IGNORECASE)


def derive_search_terms(error_code: str, error_field: str) -> list[str]:
    """Derive Jira search terms from a finding's error field.

    The error field carries a mapping-catalog prefix that never appears in
    operational tickets, so it is stripped to produce meaningful search terms.
    Example: ``CORORA-R-ERR-NO-SEC-TERM-OVRD`` ->
    ``["ERR-NO-SEC-TERM-OVRD", "NO-SEC-TERM-OVRD"]``.

    Falls back to the 2-character error code only when no field is available.
    """
    terms: list[str] = []
    field = (error_field or "").strip()
    if field:
        core = _MAPPING_PREFIX_RE.sub("", field).strip("-").strip()
        if core:
            terms.append(core)
            stripped = _ERROR_PREFIX_RE.sub("", core).strip("-").strip()
            if stripped and stripped.upper() != core.upper():
                terms.append(stripped)
    if not terms:
        code = (error_code or "").strip()
        if code:
            terms.append(code)

    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        key = term.upper()
        if key not in seen:
            seen.add(key)
            unique.append(term)
    return unique


def build_jql(
    terms: list[str],
    *,
    projects: list[str] | None = None,
    extra_jql: str = "",
) -> str:
    """Compose a JQL query that finds tickets mentioning the given terms.

    Uses exact-phrase matching (``text ~ "\\"term\\""``) so Jira does not match
    the individual tokens loosely (e.g. "ship" or "via" on their own).
    """
    clean_terms = [t.strip() for t in terms if t and t.strip()]
    clauses: list[str] = []
    if clean_terms:
        # Wrap each term in escaped quotes for a phrase match, not a token match.
        text_terms = " OR ".join(f'text ~ "\\"{_escape_jql(t)}\\""' for t in clean_terms)
        clauses.append(f"({text_terms})")
    if projects:
        joined = ", ".join(f'"{_escape_jql(p)}"' for p in projects)
        clauses.append(f"project in ({joined})")
    if extra_jql.strip():
        clauses.append(f"({extra_jql.strip()})")
    where = " AND ".join(clauses) if clauses else "created >= -365d"
    return f"{where} ORDER BY updated DESC"


def _adf_to_text(node: Any) -> str:
    """Flatten Atlassian Document Format (API v3) into plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(_adf_to_text(item) for item in node)
    if isinstance(node, dict):
        node_type = node.get("type")
        if node_type == "text":
            return str(node.get("text", ""))
        pieces = [_adf_to_text(node.get("content"))]
        text = " ".join(p for p in pieces if p)
        if node_type in {"paragraph", "heading", "listItem", "blockquote", "codeBlock"}:
            return text + "\n"
        return text
    return ""


def _normalize_ws(text: str) -> str:
    return " ".join(text.split())


def _extract_comments(fields: dict[str, Any]) -> list[dict[str, str]]:
    comment_container = fields.get("comment") or {}
    raw_comments = comment_container.get("comments") if isinstance(comment_container, dict) else None
    if not isinstance(raw_comments, list):
        return []
    out: list[dict[str, str]] = []
    for comment in raw_comments:
        if not isinstance(comment, dict):
            continue
        author = ""
        author_obj = comment.get("author")
        if isinstance(author_obj, dict):
            author = str(author_obj.get("displayName") or "")
        body = comment.get("body")
        text = _normalize_ws(_adf_to_text(body) if not isinstance(body, str) else body)
        out.append(
            {
                "author": author,
                "created": str(comment.get("created") or ""),
                "text": text,
            }
        )
    return out


def _terms_in_text(text: str, terms: list[str]) -> list[str]:
    """Return the search terms (in order) that appear in ``text``."""
    if not text or not terms:
        return []
    lowered = text.lower()
    return [t for t in terms if t and t.lower() in lowered]


def _mention_snippet(
    text: str,
    terms: list[str],
    *,
    radius: int = _MENTION_RADIUS,
    max_len: int = _MAX_MENTION_LEN,
) -> str:
    """Return an excerpt centered on the first search-term occurrence."""
    if not text or not terms:
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
        return ""
    start = max(0, first - radius)
    end = min(len(text), first + radius)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "… " + snippet
    if end < len(text):
        snippet = snippet + " …"
    return snippet[:max_len]


def _collect_mentions(
    description: str, comments: list[dict[str, str]], terms: list[str]
) -> list[dict[str, str]]:
    """Snippets from description/comments where a search term is mentioned."""
    mentions: list[dict[str, str]] = []
    if not terms:
        return mentions
    if description and _terms_in_text(description, terms):
        snippet = _mention_snippet(description, terms)
        if snippet:
            mentions.append({"source": "Description", "author": "", "snippet": snippet})
    for comment in comments:
        text = comment.get("text", "")
        if text and _terms_in_text(text, terms):
            snippet = _mention_snippet(text, terms)
            if snippet:
                mentions.append(
                    {
                        "source": "Comment",
                        "author": comment.get("author", ""),
                        "snippet": snippet,
                    }
                )
    return mentions


def _pick_resolution_excerpt(
    description: str, comments: list[dict[str, str]], terms: list[str]
) -> str:
    """Choose the best excerpt: prefer text that mentions a search term.

    Priority: (1) text with a search term AND resolution language,
    (2) text with a search term, (3) resolution language, (4) latest text.
    """
    candidates: list[str] = []
    # Prefer the latest comments (Jira returns them oldest-first).
    for comment in reversed(comments):
        text = comment.get("text", "").strip()
        if text:
            candidates.append(text)
    if description.strip():
        candidates.append(description.strip())

    def has_keyword(text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in _RESOLUTION_KEYWORDS)

    def has_term(text: str) -> bool:
        return bool(_terms_in_text(text, terms))

    for predicate in (
        lambda t: has_term(t) and has_keyword(t),
        has_term,
        has_keyword,
    ):
        for text in candidates:
            if predicate(text):
                return text[:_MAX_EXCERPT_LEN]
    return (candidates[0][:_MAX_EXCERPT_LEN]) if candidates else ""


def analyze_issue(
    issue: dict[str, Any], base_url: str, search_terms: list[str] | None = None
) -> dict[str, Any]:
    """Turn a raw Jira issue into a compact, resolution-focused record."""
    terms = search_terms or []
    fields = issue.get("fields") or {}
    key = str(issue.get("key") or "")

    status_obj = fields.get("status") or {}
    status = str(status_obj.get("name") or "") if isinstance(status_obj, dict) else ""
    status_category = ""
    if isinstance(status_obj, dict):
        category = status_obj.get("statusCategory") or {}
        if isinstance(category, dict):
            status_category = str(category.get("key") or "")

    resolution_obj = fields.get("resolution") or {}
    resolution = (
        str(resolution_obj.get("name") or "") if isinstance(resolution_obj, dict) else ""
    )

    assignee_obj = fields.get("assignee") or {}
    assignee = (
        str(assignee_obj.get("displayName") or "") if isinstance(assignee_obj, dict) else ""
    )

    priority_obj = fields.get("priority") or {}
    priority = str(priority_obj.get("name") or "") if isinstance(priority_obj, dict) else ""

    issuetype_obj = fields.get("issuetype") or {}
    issue_type = (
        str(issuetype_obj.get("name") or "") if isinstance(issuetype_obj, dict) else ""
    )

    labels = [str(item) for item in (fields.get("labels") or []) if item]

    description_raw = fields.get("description")
    description = _normalize_ws(
        _adf_to_text(description_raw) if not isinstance(description_raw, str) else description_raw
    )
    summary = str(fields.get("summary") or "")
    comments = _extract_comments(fields)
    resolution_excerpt = _pick_resolution_excerpt(description, comments, terms)

    mentions: list[dict[str, str]] = []
    if terms and summary and _terms_in_text(summary, terms):
        summary_snippet = _mention_snippet(summary, terms)
        if summary_snippet:
            mentions.append({"source": "Summary", "author": "", "snippet": summary_snippet})
    mentions.extend(_collect_mentions(description, comments, terms))

    combined = " ".join([summary, description] + [c.get("text", "") for c in comments])
    matched_terms = _terms_in_text(combined, terms)

    is_resolved = bool(resolution) or status_category == "done"

    return {
        "key": key,
        "url": f"{base_url.rstrip('/')}/browse/{key}" if base_url and key else "",
        "summary": summary,
        "status": status,
        "status_category": status_category,
        "is_resolved": is_resolved,
        "resolution": resolution,
        "resolution_excerpt": resolution_excerpt,
        "mentions": mentions,
        "matched_terms": matched_terms,
        "issue_type": issue_type,
        "priority": priority,
        "assignee": assignee,
        "labels": labels,
        "updated": str(fields.get("updated") or ""),
        "comment_count": len(comments),
    }


def _summarize(
    issues: list[dict[str, Any]], search_terms: list[str]
) -> tuple[str, list[str]]:
    terms = " / ".join(t for t in search_terms if t) or "the finding"
    if not issues:
        return (f"No Jira tickets mention {terms}.", [])
    resolved = [i for i in issues if i["is_resolved"]]
    lines: list[str] = []
    summary = (
        f"Found {len(issues)} Jira ticket(s) referencing {terms}; "
        f"{len(resolved)} appear resolved."
    )
    for issue in resolved[:3]:
        excerpt = issue["resolution_excerpt"] or issue["summary"]
        label = issue["resolution"] or issue["status"] or "resolved"
        lines.append(f"{issue['key']} ({label}): {excerpt}"[:_MAX_EXCERPT_LEN])
    if not lines:
        for issue in issues[:3]:
            lines.append(f"{issue['key']} ({issue['status'] or 'open'}): {issue['summary']}")
    return summary, lines


# --------------------------------------------------------------------------- #
# Mock support (local development / automated tests without a live Jira)       #
# --------------------------------------------------------------------------- #

_BUILTIN_MOCK_ISSUES: list[dict[str, Any]] = [
    {
        "key": "OPS-4821",
        "fields": {
            "summary": "EV / ERROR-SHIP-VIA rejects valid ship-via codes in ORP676",
            "status": {"name": "Done", "statusCategory": {"key": "done"}},
            "resolution": {"name": "Fixed"},
            "assignee": {"displayName": "Priya Nair"},
            "priority": {"name": "High"},
            "issuetype": {"name": "Bug"},
            "labels": ["cobol", "shipping"],
            "updated": "2026-02-11T09:32:00.000+0000",
            "description": "Orders fail edit EV on ERROR-SHIP-VIA when the carrier "
            "code is lowercase.",
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "Sam Ortiz"},
                        "created": "2026-02-10T14:00:00.000+0000",
                        "body": "Reproduced with order P28062375.",
                    },
                    {
                        "author": {"displayName": "Priya Nair"},
                        "created": "2026-02-11T09:30:00.000+0000",
                        "body": "Root cause: CORORA-R-ERROR-SHIP-VIA table was "
                        "missing upper-cased carrier aliases. Resolution: added the "
                        "aliases and normalized ship-via to upper case in "
                        "120-EDIT-SHIPMENT-HEADER before the EV edit. Deployed in "
                        "release 26.1.3.",
                    },
                ]
            },
        },
    },
    {
        "key": "OPS-5099",
        "fields": {
            "summary": "SE edit: ERR-NO-SEC-TERM-OVRD blocks valid secondary-term overrides",
            "status": {"name": "Done", "statusCategory": {"key": "done"}},
            "resolution": {"name": "Fixed"},
            "assignee": {"displayName": "Marcus Vogel"},
            "priority": {"name": "High"},
            "issuetype": {"name": "Bug"},
            "labels": ["cobol", "security"],
            "updated": "2026-03-04T11:15:00.000+0000",
            "description": "Orders with a security term override are rejected on "
            "ERR-NO-SEC-TERM-OVRD during the SE edit.",
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "Marcus Vogel"},
                        "created": "2026-03-04T11:10:00.000+0000",
                        "body": "Root cause: the NO-SEC-TERM-OVRD flag was not being "
                        "set for pre-authorized accounts. Resolution: populate the "
                        "override flag in 200-VALIDATE-SECURITY before the SE edit and "
                        "skip ERR-NO-SEC-TERM-OVRD when the account is allow-listed. "
                        "Shipped in release 26.2.0.",
                    }
                ]
            },
        },
    },
    {
        "key": "OPS-4655",
        "fields": {
            "summary": "Intermittent EV edit failures during peak checkout",
            "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
            "resolution": None,
            "assignee": {"displayName": "Dana Lee"},
            "priority": {"name": "Medium"},
            "issuetype": {"name": "Incident"},
            "labels": ["checkout"],
            "updated": "2026-01-28T18:05:00.000+0000",
            "description": "Some checkout orders hit ERROR-SHIP-VIA under load; "
            "investigating a caching workaround.",
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "Dana Lee"},
                        "created": "2026-01-28T18:00:00.000+0000",
                        "body": "Workaround: retry the edit after refreshing the "
                        "ship-via cache; permanent fix pending.",
                    }
                ]
            },
        },
    },
]


def _load_mock_issues(config: JiraConfig) -> list[dict[str, Any]]:
    token = config.mock.strip()
    if token in {"1", "builtin", "true", "True", ""}:
        return list(_BUILTIN_MOCK_ISSUES)
    path = os.path.expanduser(token)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("issues"), list):
            return data["issues"]
        if isinstance(data, list):
            return data
    return list(_BUILTIN_MOCK_ISSUES)


def _mock_matches(issue: dict[str, Any], terms: list[str]) -> bool:
    lowered = [t.strip().lower() for t in terms if t and t.strip()]
    if not lowered:
        return True
    fields = issue.get("fields") or {}
    hay = json.dumps(fields).lower()
    return any(term in hay for term in lowered)


def search_for_finding(
    error_code: str,
    error_field: str,
    *,
    config: JiraConfig | None = None,
) -> dict[str, Any]:
    """Search Jira for tickets related to a finding and summarize resolutions."""
    cfg = config or JiraConfig.from_env()
    terms = derive_search_terms(error_code, error_field)
    jql = build_jql(
        terms,
        projects=cfg.projects,
        extra_jql=cfg.extra_jql,
    )
    base_payload: dict[str, Any] = {
        "configured": cfg.is_configured,
        "mock": cfg.is_mock,
        "base_url": cfg.base_url,
        "query": {
            "error_code": error_code,
            "error_field": error_field,
            "terms": terms,
            "jql": jql,
        },
        "issues": [],
        "issue_count": 0,
        "total_matched": 0,
        "filtered_out": 0,
        "summary": "",
        "insights": [],
    }

    if not cfg.is_configured:
        base_payload["reachable"] = False
        base_payload["error"] = (
            "Jira is not configured. Set JIRA_BASE_URL, JIRA_EMAIL and "
            "JIRA_API_TOKEN (see README) to enable ticket search."
        )
        return base_payload

    try:
        if cfg.is_mock:
            raw_issues = [
                issue
                for issue in _load_mock_issues(cfg)
                if _mock_matches(issue, terms)
            ][: cfg.max_results]
        else:
            response = _post_json(
                cfg,
                cfg.search_path,
                {"jql": jql, "maxResults": cfg.max_results, "fields": _DEFAULT_FIELDS},
            )
            raw_issues = response.get("issues") or []
            for issue in raw_issues:
                fields = issue.get("fields") or {}
                comment = fields.get("comment")
                has_comments = isinstance(comment, dict) and comment.get("comments")
                if not has_comments:
                    fetched = _fetch_comment_container(cfg, str(issue.get("key") or ""))
                    if fetched is not None:
                        fields["comment"] = fetched
                        issue["fields"] = fields
    except JiraError as exc:
        base_payload["reachable"] = False
        base_payload["error"] = str(exc)
        return base_payload

    analyzed = [analyze_issue(issue, cfg.base_url, terms) for issue in raw_issues]
    total_matched = len(analyzed)
    # Hide loose JQL-only matches: keep tickets that literally mention a term
    # (in summary, description, or comments). Only filter when we have terms.
    issues = [i for i in analyzed if i["matched_terms"]] if terms else analyzed
    filtered_out = total_matched - len(issues)
    summary, insights = _summarize(issues, terms)
    base_payload.update(
        {
            "reachable": True,
            "issues": issues,
            "issue_count": len(issues),
            "total_matched": total_matched,
            "filtered_out": filtered_out,
            "summary": summary,
            "insights": insights,
        }
    )
    return base_payload
