"""Data models for operational document ingestion and resolution."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    email = "email"
    ticket = "ticket"
    pdf = "pdf"
    word = "word"
    runbook = "runbook"
    incident = "incident"
    chat = "chat"
    log = "log"
    csv = "csv"
    excel = "excel"
    html = "html"
    unknown = "unknown"


class ExtractedEntity(BaseModel):
    kind: str  # error_code | program_id | corora_field | symptom
    value: str
    confidence: float = 1.0
    span: str = ""


class DocumentLink(BaseModel):
    document_id: str
    program: str = ""
    error_code: str = ""
    error_field: str = ""
    score: float = 0.0
    evidence: str = ""
    finding_key: str = ""


class EvidenceItem(BaseModel):
    type: str  # cobol_finding | document
    ref: str = ""
    excerpt: str = ""
    document_id: str = ""


class ResolutionSuggestion(BaseModel):
    document_id: str
    summary: str = ""
    steps: list[str] = Field(default_factory=list)
    confidence: str = "medium"  # high | medium | low
    evidence: list[EvidenceItem] = Field(default_factory=list)
    provider: str = "heuristic"


class OperationalDocument(BaseModel):
    id: str
    source_path: Path
    doc_type: DocumentType = DocumentType.unknown
    title: str = ""
    body_text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunks: list[str] = Field(default_factory=list)
    search_text: str = ""
    ingested_at: str = ""
    entities: list[ExtractedEntity] = Field(default_factory=list)
    links: list[DocumentLink] = Field(default_factory=list)
    resolution: ResolutionSuggestion | None = None


class IngestManifest(BaseModel):
    root: Path
    documents: list[OperationalDocument] = Field(default_factory=list)
    generated_at: str = ""

    def to_document_records(self, *, focused_scan: bool = False) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for doc in self.documents:
            if focused_scan and not doc.metadata.get("term_matched"):
                continue
            res = doc.resolution
            rows.append(
                {
                    "document_id": doc.id,
                    "source_path": str(doc.source_path),
                    "doc_type": doc.doc_type.value,
                    "title": doc.title,
                    "body_preview": (doc.body_text or "")[:500],
                    "metadata": doc.metadata,
                    "term_matched": doc.metadata.get("term_matched", False),
                    "match_reasons": doc.metadata.get("match_reasons", []),
                    "entity_count": len(doc.entities),
                    "link_count": len(doc.links),
                    "linked_programs": ",".join(
                        sorted({lnk.program for lnk in doc.links if lnk.program})
                    ),
                    "linked_error_codes": ",".join(
                        sorted({lnk.error_code for lnk in doc.links if lnk.error_code})
                    ),
                    "linked_error_fields": ",".join(
                        sorted({lnk.error_field for lnk in doc.links if lnk.error_field})
                    ),
                    "links": [
                        {
                            "finding_key": lnk.finding_key,
                            "program": lnk.program,
                            "error_code": lnk.error_code,
                            "error_field": lnk.error_field,
                            "score": lnk.score,
                            "evidence": lnk.evidence,
                        }
                        for lnk in doc.links
                    ],
                    "resolution_summary": res.summary if res else "",
                    "resolution_steps": res.steps if res else [],
                    "resolution_confidence": res.confidence if res else "",
                    "resolution_provider": res.provider if res else "",
                    "search_text": doc.search_text,
                    "ingested_at": doc.ingested_at,
                }
            )
        return rows

    def to_resolution_records(
        self,
        *,
        focused_scan: bool = False,
        finding_resolutions: list[ResolutionSuggestion] | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for fr in finding_resolutions or []:
            rows.append(_resolution_row(fr, scope="finding", title="COBOL findings"))
        for doc in self.documents:
            if focused_scan and not doc.metadata.get("term_matched"):
                continue
            if doc.resolution is None:
                continue
            res = doc.resolution
            rows.append(
                _resolution_row(
                    res,
                    scope="document",
                    title=doc.title,
                    doc_type=doc.doc_type.value,
                    linked_error_codes=",".join(
                        sorted({lnk.error_code for lnk in doc.links if lnk.error_code})
                    ),
                    linked_error_fields=",".join(
                        sorted({lnk.error_field for lnk in doc.links if lnk.error_field})
                    ),
                )
            )
        return rows


def _evidence_records(evidence: list[EvidenceItem]) -> list[dict[str, Any]]:
    from cobol_error_scanner.ingestion.knowledge_store import evidence_with_indexes

    return evidence_with_indexes(evidence)


def _resolution_row(
    res: ResolutionSuggestion,
    *,
    scope: str,
    title: str = "",
    doc_type: str = "",
    linked_error_codes: str = "",
    linked_error_fields: str = "",
) -> dict[str, Any]:
    return {
        "scope": scope,
        "document_id": res.document_id,
        "title": title,
        "doc_type": doc_type,
        "summary": res.summary,
        "steps": res.steps,
        "confidence": res.confidence,
        "evidence": _evidence_records(res.evidence),
        "provider": res.provider,
        "linked_error_codes": linked_error_codes,
        "linked_error_fields": linked_error_fields,
    }
