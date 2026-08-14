"""Word (.docx) adapter."""

from __future__ import annotations

from pathlib import Path

from cobol_error_scanner.ingestion.adapters.base import _base_document
from cobol_error_scanner.ingestion.models import DocumentType, OperationalDocument


class WordAdapter:
    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".docx"

    def extract(self, path: Path) -> OperationalDocument:
        warnings: list[str] = []
        parts: list[str] = []
        try:
            from docx import Document

            doc = Document(str(path))
            for para in doc.paragraphs:
                if para.text.strip():
                    parts.append(para.text)
        except Exception as exc:
            warnings.append(str(exc))
        body = "\n".join(parts)
        name = path.stem.lower()
        doc_type = DocumentType.word
        if "runbook" in name:
            doc_type = DocumentType.runbook
        elif "incident" in name:
            doc_type = DocumentType.incident
        return _base_document(
            path,
            doc_type=doc_type,
            title=path.stem,
            body=body,
            metadata={"warnings": warnings},
        )
