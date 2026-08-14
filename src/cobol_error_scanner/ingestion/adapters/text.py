"""Plain text and markdown adapters (runbooks, incidents)."""

from __future__ import annotations

from pathlib import Path

from cobol_error_scanner.ingestion.adapters.base import _base_document
from cobol_error_scanner.ingestion.models import DocumentType, OperationalDocument


def _infer_doc_type(path: Path) -> DocumentType:
    name = path.stem.lower()
    if "runbook" in name or "run-book" in name:
        return DocumentType.runbook
    if "incident" in name or "postmortem" in name or "post-mortem" in name:
        return DocumentType.incident
    if path.suffix.lower() == ".md":
        return DocumentType.runbook
    return DocumentType.unknown


class TextAdapter:
    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in {".txt", ".md"}

    def extract(self, path: Path) -> OperationalDocument:
        body = path.read_text(encoding="utf-8", errors="replace")
        doc_type = _infer_doc_type(path)
        return _base_document(
            path,
            doc_type=doc_type,
            title=path.stem,
            body=body,
            metadata={"format": path.suffix.lower()},
        )
