"""Chat export adapter (Slack/Teams-ish JSON and line-oriented text)."""

from __future__ import annotations

import json
from pathlib import Path

from cobol_error_scanner.ingestion.adapters.base import _base_document
from cobol_error_scanner.ingestion.models import DocumentType, OperationalDocument

_CHAT_KEYS = ("text", "message", "body", "content", "user", "sender", "timestamp", "ts")


def _is_chat_json(path: Path) -> bool:
    name = path.stem.lower()
    return any(tok in name for tok in ("chat", "slack", "teams", "conversation", "messages"))


def _lines_from_json(data: object) -> list[str]:
    lines: list[str] = []
    if isinstance(data, list):
        for item in data[:500]:
            lines.extend(_lines_from_json(item))
    elif isinstance(data, dict):
        user = data.get("user") or data.get("sender") or data.get("author") or ""
        text = data.get("text") or data.get("message") or data.get("body") or data.get("content") or ""
        if isinstance(text, str) and text.strip():
            prefix = f"{user}: " if user else ""
            lines.append(prefix + text.strip())
        for k, v in data.items():
            if k not in _CHAT_KEYS and isinstance(v, (dict, list)):
                lines.extend(_lines_from_json(v))
    return lines


class ChatAdapter:
    def supports(self, path: Path) -> bool:
        suf = path.suffix.lower()
        if suf == ".json" and _is_chat_json(path):
            return True
        if suf in {".txt", ".csv"}:
            name = path.stem.lower()
            return any(tok in name for tok in ("chat", "slack", "teams", "conversation"))
        return False

    def extract(self, path: Path) -> OperationalDocument:
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            lines = _lines_from_json(data)
            body = "\n".join(lines)
        else:
            body = path.read_text(encoding="utf-8", errors="replace")
        return _base_document(
            path,
            doc_type=DocumentType.chat,
            title=path.stem,
            body=body,
            metadata={"format": path.suffix.lower()},
        )
