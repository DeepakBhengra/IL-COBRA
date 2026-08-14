"""HTML (.html, .htm) adapter."""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path

from cobol_error_scanner.ingestion.adapters.base import _base_document
from cobol_error_scanner.ingestion.models import DocumentType, OperationalDocument

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)


def _extract_title(raw: str) -> str:
    match = _TITLE_RE.search(raw)
    if not match:
        return ""
    return unescape(re.sub(r"\s+", " ", match.group(1))).strip()


def _html_to_text(raw: str) -> str:
    """Best-effort HTML to plain text without extra dependencies."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        return unescape(text)
    except ImportError:
        cleaned = _SCRIPT_STYLE_RE.sub(" ", raw)
        cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"</(p|div|h[1-6]|li|tr)>", "\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        return unescape(cleaned)


class HtmlAdapter:
    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in {".html", ".htm"}

    def extract(self, path: Path) -> OperationalDocument:
        raw = path.read_text(encoding="utf-8", errors="replace")
        body = _html_to_text(raw)
        title = _extract_title(raw) or path.stem
        name = path.stem.lower()
        doc_type = DocumentType.html
        if "runbook" in name:
            doc_type = DocumentType.runbook
        elif "incident" in name:
            doc_type = DocumentType.incident
        return _base_document(
            path,
            doc_type=doc_type,
            title=title,
            body=body,
            metadata={"format": path.suffix.lower()},
        )
