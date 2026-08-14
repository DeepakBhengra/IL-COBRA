"""Document adapter protocol and routing."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from cobol_error_scanner.ingestion.models import DocumentType, OperationalDocument
from cobol_error_scanner.ingestion.normalize import build_search_text, chunk_text, normalize_body


class DocumentAdapter(Protocol):
    def supports(self, path: Path) -> bool: ...
    def extract(self, path: Path) -> OperationalDocument: ...


def document_id_for(path: Path) -> str:
    digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
    return f"doc-{digest}"


def _base_document(
    path: Path,
    *,
    doc_type: DocumentType,
    title: str,
    body: str,
    metadata: dict | None = None,
    chunk_chars: int = 2000,
) -> OperationalDocument:
    body_norm = normalize_body(body)
    meta = dict(metadata or {})
    now = datetime.now(timezone.utc).isoformat()
    return OperationalDocument(
        id=document_id_for(path),
        source_path=path.resolve(),
        doc_type=doc_type,
        title=title or path.stem,
        body_text=body_norm,
        metadata=meta,
        chunks=chunk_text(body_norm, chunk_chars=chunk_chars),
        search_text=build_search_text(
            title=title or path.stem,
            body=body_norm,
            doc_type=doc_type.value,
            metadata=meta,
        ),
        ingested_at=now,
    )
