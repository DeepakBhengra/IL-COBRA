"""Fallback adapter for unrecognized but allowed suffixes."""

from __future__ import annotations

from pathlib import Path

from cobol_error_scanner.ingestion.adapters.base import _base_document
from cobol_error_scanner.ingestion.models import DocumentType, OperationalDocument


class UnknownAdapter:
    def supports(self, path: Path) -> bool:
        return True

    def extract(self, path: Path) -> OperationalDocument:
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            body = ""
            return _base_document(
                path,
                doc_type=DocumentType.unknown,
                title=path.stem,
                body=body,
                metadata={"warning": str(exc)},
            )
        return _base_document(
            path,
            doc_type=DocumentType.unknown,
            title=path.stem,
            body=body,
            metadata={"format": path.suffix.lower()},
        )
