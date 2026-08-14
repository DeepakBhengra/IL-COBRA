"""Enrich COBOL finding summaries with operational document context."""

from __future__ import annotations

from pathlib import Path

from cobol_error_scanner.ingestion.document_search import (
    find_matching_documents,
    summarize_document_matches,
)
from cobol_error_scanner.ingestion.search_terms import collect_search_terms
from cobol_error_scanner.models import ProgramSummary, ScanManifest

_DOC_SECTION_HEADER = "--- From operational documents ---"


def resolve_docs_root(source_root: Path, docs_root: Path | None = None) -> Path | None:
    if docs_root is not None:
        p = docs_root.resolve()
        return p if p.is_dir() else None
    from cobol_error_scanner.ingestion.scanner import iter_document_files
    from cobol_error_scanner.project_paths import repo_root

    for candidate in (source_root / "docs", repo_root() / "samples" / "docs"):
        if candidate.is_dir() and iter_document_files(candidate):
            return candidate.resolve()
    return None


def enrich_programs_from_documents(
    programs: list[ProgramSummary],
    docs_root: Path,
    *,
    focused_error_code: str = "",
    focused_error_field: str = "",
) -> str:
    """
    Scan operational documents and append context to each occurrence's ``row_summary``.
    Returns the operational summary text (empty if docs_root missing).
    """
    terms = collect_search_terms(
        programs,
        focused_error_code=focused_error_code,
        focused_error_field=focused_error_field,
    )
    matches = find_matching_documents(
        docs_root,
        error_codes=terms["error_codes"],
        error_fields=terms["error_fields"],
        field_aliases=terms["field_aliases"],
    )
    if not matches:
        for prog in programs:
            for occ in prog.occurrences:
                base = (occ.row_summary or "").strip()
                if _DOC_SECTION_HEADER in base:
                    occ.row_summary = base.split(_DOC_SECTION_HEADER)[0].strip()
        return ""

    doc_summary = summarize_document_matches(
        matches,
        error_codes=terms["error_codes"],
        error_fields=terms["error_fields"],
        field_aliases=terms["field_aliases"],
    )

    for prog in programs:
        for occ in prog.occurrences:
            base = (occ.row_summary or "").strip()
            if _DOC_SECTION_HEADER in base:
                base = base.split(_DOC_SECTION_HEADER)[0].strip()
            occ.row_summary = f"{base}\n\n{_DOC_SECTION_HEADER}\n{doc_summary}".strip()
    return doc_summary


def enrich_manifest_from_documents(
    manifest: ScanManifest,
    docs_root: Path | None = None,
    *,
    focused_error_code: str = "",
    focused_error_field: str = "",
) -> tuple[ScanManifest, Path | None]:
    root = resolve_docs_root(manifest.root, docs_root)
    if root is None:
        return manifest, None
    enrich_programs_from_documents(
        manifest.programs,
        root,
        focused_error_code=focused_error_code,
        focused_error_field=focused_error_field,
    )
    return manifest, root
