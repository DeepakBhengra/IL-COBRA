"""Support ticket export adapter (.json, .csv)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from cobol_error_scanner.ingestion.adapters.base import _base_document
from cobol_error_scanner.ingestion.models import DocumentType, OperationalDocument

_TICKET_TEXT_KEYS = (
    "description",
    "summary",
    "body",
    "text",
    "comments",
    "short_description",
    "work_notes",
    "message",
)


def _collect_strings(obj: object, depth: int = 0) -> list[str]:
    if depth > 6:
        return []
    if isinstance(obj, str) and obj.strip():
        return [obj]
    if isinstance(obj, dict):
        out: list[str] = []
        for k, v in obj.items():
            if str(k).lower() in _TICKET_TEXT_KEYS:
                out.extend(_collect_strings(v, depth + 1))
            elif isinstance(v, (dict, list)):
                out.extend(_collect_strings(v, depth + 1))
        return out
    if isinstance(obj, list):
        out: list[str] = []
        for item in obj[:50]:
            out.extend(_collect_strings(item, depth + 1))
        return out
    return []


def _ticket_meta(obj: dict) -> dict:
    meta: dict = {}
    for key in ("id", "key", "number", "ticket_id", "sys_id", "status", "priority", "severity"):
        if key in obj:
            meta[key] = obj[key]
    return meta


class TicketAdapter:
    def supports(self, path: Path) -> bool:
        if path.suffix.lower() not in {".json", ".csv"}:
            return False
        name = path.stem.lower()
        return any(tok in name for tok in ("ticket", "jira", "servicenow", "issue", "case"))

    def extract(self, path: Path) -> OperationalDocument:
        if path.suffix.lower() == ".json":
            return self._from_json(path)
        return self._from_csv(path)

    def _from_json(self, path: Path) -> OperationalDocument:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, list) and data:
            data = data[0]
        if not isinstance(data, dict):
            data = {"raw": str(data)}
        parts = _collect_strings(data)
        body = "\n\n".join(parts) if parts else json.dumps(data, indent=2)
        title = str(data.get("summary") or data.get("title") or path.stem)
        meta = _ticket_meta(data)
        return _base_document(
            path,
            doc_type=DocumentType.ticket,
            title=title,
            body=body,
            metadata=meta,
        )

    def _from_csv(self, path: Path) -> OperationalDocument:
        rows: list[dict[str, str]] = []
        with path.open(encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if i >= 100:
                    break
                rows.append({k: (v or "") for k, v in row.items()})
        parts: list[str] = []
        meta: dict = {}
        for row in rows[:20]:
            for k, v in row.items():
                kl = k.lower()
                if kl in _TICKET_TEXT_KEYS and v.strip():
                    parts.append(v)
                if kl in ("id", "key", "number", "ticket_id") and v.strip() and "ticket_id" not in meta:
                    meta["ticket_id"] = v
        body = "\n\n".join(parts) if parts else "\n".join(
            ", ".join(f"{k}={v}" for k, v in r.items() if v) for r in rows[:10]
        )
        return _base_document(
            path,
            doc_type=DocumentType.ticket,
            title=path.stem,
            body=body,
            metadata=meta,
        )
