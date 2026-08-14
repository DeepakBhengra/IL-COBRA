"""PDF adapter."""

from __future__ import annotations

from pathlib import Path

from cobol_error_scanner.ingestion.adapters.base import _base_document
from cobol_error_scanner.ingestion.models import DocumentType, OperationalDocument


class PdfAdapter:
    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def extract(self, path: Path) -> OperationalDocument:
        warnings: list[str] = []
        parts: list[str] = []
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            for page in reader.pages:
                text = page.extract_text() or ""
                if text.strip():
                    parts.append(text)
        except Exception as exc:
            warnings.append(str(exc))
        body = "\n\n".join(parts)
        return _base_document(
            path,
            doc_type=DocumentType.pdf,
            title=path.stem,
            body=body,
            metadata={"page_count": len(parts), "warnings": warnings},
        )
