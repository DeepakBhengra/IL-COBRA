"""Text normalization and chunking for operational documents."""

from __future__ import annotations

import re

_HTML_TAG = re.compile(r"<[^>]+>")
_WS_COLLAPSE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def strip_html(text: str) -> str:
    return _HTML_TAG.sub(" ", text)


def normalize_body(text: str) -> str:
    t = strip_html(text or "")
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = _WS_COLLAPSE.sub(" ", t)
    lines = [ln.strip() for ln in t.split("\n")]
    t = "\n".join(lines)
    t = _BLANK_LINES.sub("\n\n", t)
    return t.strip()


def chunk_text(text: str, *, chunk_chars: int = 2000) -> list[str]:
    if not text:
        return []
    if len(text) <= chunk_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        if end < len(text):
            break_at = text.rfind("\n", start, end)
            if break_at > start + chunk_chars // 2:
                end = break_at + 1
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


def build_search_text(
    *,
    title: str = "",
    body: str = "",
    doc_type: str = "",
    metadata: dict | None = None,
) -> str:
    parts = [title, doc_type, body]
    if metadata:
        for key in ("ticket_id", "sender", "subject", "severity", "status"):
            val = metadata.get(key)
            if val:
                parts.append(str(val))
    return " ".join(p for p in parts if p).strip()
