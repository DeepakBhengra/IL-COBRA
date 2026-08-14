"""End-to-end document ingestion pipeline."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cobol_error_scanner.config_loader import AppConfig, load_app_config
from cobol_error_scanner.llm_client import LLM_PROVIDERS
from cobol_error_scanner.ingestion.adapters import extract_document
from cobol_error_scanner.ingestion.adapters.base import document_id_for
from cobol_error_scanner.ingestion.finding_resolution import build_finding_resolution
from cobol_error_scanner.ingestion.knowledge_store import (
    accepted_evidence_items,
    codes_for_document,
    get_confirmed_resolution,
    has_high_confidence_accepted,
    knowledge_dir,
    load_cached_document,
    load_document_records,
    load_documents_for_index_entry,
    load_historical_documents,
    load_index,
    load_operational_document_by_id,
    load_resolutions_for_index_entry,
    lookup_code_field_index,
    needs_extract,
    resolution_from_accepted_evidence,
    resolutions_for_codes,
    skip_resolve_document_ids,
    update_index_entry,
)
from cobol_error_scanner.ingestion.linker import link_documents, load_finding_rows
from cobol_error_scanner.ingestion.models import IngestManifest, OperationalDocument, ResolutionSuggestion
from cobol_error_scanner.ingestion.resolution import (
    ResolverConfig,
    build_documents_by_id,
    retrieve_similar,
    suggest_resolution,
)
from cobol_error_scanner.ingestion.scanner import iter_document_files
from cobol_error_scanner.ingestion.search_terms import strict_terms_from_focused_scan

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _redact_text(text: str) -> str:
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _SSN_RE.sub("[REDACTED_SSN]", text)
    return text


def _finding_index(rows: list[dict]) -> dict[str, dict]:
    from cobol_error_scanner.ingestion.linker import _finding_key

    return {_finding_key(row): row for row in rows}


def _ingest_fast_path_from_accepted(
    docs_root: Path,
    *,
    rows: list[dict],
    primary_code: str,
    accepted_ev: dict[str, Any],
    focused_error_code: str,
    focused_error_field: str,
    kdir: Path,
    cfg: AppConfig,
) -> tuple[IngestManifest, list[ResolutionSuggestion]]:
    """Skip folder walk when user-confirmed evidence exists for a focused code."""
    code = primary_code.strip().upper()
    accepted_resolution = resolution_from_accepted_evidence(code, accepted_ev, scope="finding")
    documents: list[OperationalDocument] = []
    items = accepted_evidence_items(accepted_ev)
    loaded_ids: set[str] = set()
    has_cobol_only = False
    for item in items:
        ev_type = str(item.get("type", "")).lower()
        ev_doc_id = str(item.get("document_id", "")).strip()
        if ev_type == "cobol_finding" or not ev_doc_id:
            has_cobol_only = has_cobol_only or ev_type == "cobol_finding"
            continue
        if ev_doc_id in loaded_ids:
            continue
        doc = load_operational_document_by_id(ev_doc_id, kdir=kdir, cfg=cfg)
        if doc is None:
            continue
        loaded_ids.add(ev_doc_id)
        doc.metadata["reuse_from_knowledge"] = True
        doc.metadata["term_matched"] = True
        doc.resolution = resolution_from_accepted_evidence(
            code, accepted_ev, scope="document", item=item
        )
        documents.append(doc)

    finding_resolutions: list[ResolutionSuggestion] = [accepted_resolution]
    if not documents and rows:
        fr = build_finding_resolution(
            rows,
            focused_error_code=focused_error_code or code,
            focused_error_field=focused_error_field,
        )
        if fr and has_cobol_only:
            finding_resolutions = [accepted_resolution]

    return (
        IngestManifest(
            root=docs_root.resolve(),
            documents=documents,
            generated_at=datetime.now(timezone.utc).isoformat(),
        ),
        finding_resolutions,
    )


def ingest_root(
    docs_root: Path,
    *,
    scan_out: Path,
    rules_path: Path | None = None,
    resolver: str = "heuristic",
    redact: bool = False,
    app_config: AppConfig | None = None,
    focused_error_code: str = "",
    focused_error_field: str = "",
) -> tuple[IngestManifest, list[ResolutionSuggestion]]:
    cfg = app_config or load_app_config()
    max_bytes = cfg.ingest.max_file_mb * 1024 * 1024
    errors_jsonl = scan_out / "errors.jsonl"
    rows = load_finding_rows(errors_jsonl)
    kdir = knowledge_dir(cfg)

    focused_requested = bool(focused_error_code.strip() or focused_error_field.strip())
    primary_code_early = focused_error_code.strip().upper()
    if focused_requested and cfg.knowledge.index_by_code_field and cfg.knowledge.skip_full_doc_scan_when_accepted:
        index_entry_fast = lookup_code_field_index(
            primary_code_early,
            focused_error_field=focused_error_field,
            errors_rows=rows,
            kdir=kdir,
            cfg=cfg,
        )
        if not primary_code_early:
            for row in rows:
                c = str(row.get("error_code", "")).upper()
                if c:
                    primary_code_early = c
                    break
        accepted_fast = index_entry_fast.get("accepted_evidence") or {}
        if primary_code_early and has_high_confidence_accepted(accepted_fast):
            return _ingest_fast_path_from_accepted(
                docs_root,
                rows=rows,
                primary_code=primary_code_early,
                accepted_ev=accepted_fast,
                focused_error_code=focused_error_code,
                focused_error_field=focused_error_field,
                kdir=kdir,
                cfg=cfg,
            )

    paths = iter_document_files(docs_root)
    if len(paths) > cfg.ingest.max_documents:
        paths = paths[: cfg.ingest.max_documents]

    ingest_index = load_index(kdir, cfg=cfg) if cfg.knowledge.incremental else {}

    primary_code_early = focused_error_code.strip().upper()
    index_entry_early: dict = {}
    skip_ids_early: set[str] = set()
    if primary_code_early and cfg.knowledge.index_by_code_field:
        index_entry_early = lookup_code_field_index(
            primary_code_early,
            focused_error_field=focused_error_field,
            kdir=kdir,
            cfg=cfg,
        )
        skip_ids_early = skip_resolve_document_ids(index_entry_early, cfg=cfg)

    documents: list[OperationalDocument] = []
    for path in paths:
        try:
            if path.stat().st_size > max_bytes:
                continue
            path_doc_id = document_id_for(path)
            unchanged = cfg.knowledge.incremental and not needs_extract(
                path, ingest_index, cfg=cfg
            )
            if unchanged:
                cached = load_cached_document(path, kdir=kdir, cfg=cfg)
                if cached is not None:
                    if path_doc_id in skip_ids_early:
                        cached.metadata["reuse_from_knowledge"] = True
                    documents.append(cached)
                    continue
            doc = extract_document(path)
            if redact:
                doc.body_text = _redact_text(doc.body_text)
                doc.search_text = _redact_text(doc.search_text)
            documents.append(doc)
            if cfg.knowledge.incremental:
                update_index_entry(path, document_id_for(path), ingest_index)
        except Exception as exc:
            from cobol_error_scanner.ingestion.adapters.base import _base_document
            from cobol_error_scanner.ingestion.models import DocumentType

            doc = _base_document(
                path,
                doc_type=DocumentType.unknown,
                title=path.stem,
                body="",
                metadata={"ingest_error": str(exc)},
            )
            documents.append(doc)

    strict_terms: dict[str, set[str]] | None = None
    scan_codes = {
        str(r.get("error_code", "")).upper()
        for r in rows
        if r.get("error_code")
    }
    auto_scope = not focused_error_code.strip() and not focused_error_field.strip() and bool(scan_codes)
    if focused_error_code.strip() or focused_error_field.strip() or auto_scope:
        effective_code = focused_error_code
        if auto_scope and len(scan_codes) == 1:
            effective_code = next(iter(scan_codes))
        strict_terms = strict_terms_from_focused_scan(
            rows,
            focused_error_code=effective_code,
            focused_error_field=focused_error_field,
        )

    documents = link_documents(
        documents, errors_jsonl, rules_path=rules_path, strict_terms=strict_terms
    )
    findings_by_key = _finding_index(rows)

    res_cfg = ResolverConfig(
        provider=resolver if resolver in LLM_PROVIDERS else cfg.resolver.provider,
        model=cfg.resolver.model,
        api_key_env=cfg.resolver.api_key_env,
        base_url=cfg.resolver.base_url,
        top_k=cfg.resolver.top_k,
    )

    focused_mode = strict_terms is not None
    matched_docs = [d for d in documents if d.metadata.get("term_matched")]
    current_ids = {d.id for d in documents}

    index_entry: dict = {}
    primary_code = focused_error_code.strip().upper()
    if not primary_code and focused_mode and rows:
        for row in rows:
            c = str(row.get("error_code", "")).upper()
            if c:
                primary_code = c
                break

    if focused_mode and cfg.knowledge.index_by_code_field and primary_code:
        index_entry = lookup_code_field_index(
            primary_code,
            focused_error_field=focused_error_field,
            errors_rows=rows,
            kdir=kdir,
            cfg=cfg,
        )
        historical_docs = load_documents_for_index_entry(
            index_entry, exclude_ids=current_ids, kdir=kdir, cfg=cfg
        )
        index_history = load_resolutions_for_index_entry(index_entry, kdir=kdir, cfg=cfg)
        aggregated = index_entry.get("aggregated_resolution") or {}
        skip_ids = skip_resolve_document_ids(index_entry, cfg=cfg)
    else:
        historical_docs = load_historical_documents(exclude_ids=current_ids, kdir=kdir, cfg=cfg)
        index_history = []
        aggregated = {}
        skip_ids = set()

    accepted_ev = index_entry.get("accepted_evidence") or {}
    confirmed_res = (
        get_confirmed_resolution(primary_code, kdir=kdir, cfg=cfg)
        if focused_mode and primary_code
        else {}
    )
    accepted_resolution: ResolutionSuggestion | None = None
    if focused_mode and primary_code and has_high_confidence_accepted(accepted_ev):
        accepted_resolution = resolution_from_accepted_evidence(
            primary_code, accepted_ev, scope="finding"
        )

    documents_by_id = build_documents_by_id(
        documents,
        historical_docs,
        stored_records=load_document_records(kdir, cfg=cfg),
    )

    for doc in documents:
        if focused_mode and not doc.metadata.get("term_matched"):
            doc.resolution = None
            continue
        if (
            doc.id in skip_ids
            and doc.metadata.get("reuse_from_knowledge")
            and accepted_ev
        ):
            matched_item = None
            for item in accepted_evidence_items(accepted_ev):
                if doc.id == str(item.get("document_id", "")).strip():
                    matched_item = item
                    break
            if matched_item is not None:
                doc.resolution = resolution_from_accepted_evidence(
                    primary_code or focused_error_code,
                    accepted_ev,
                    scope="document",
                    item=matched_item,
                )
            else:
                doc.resolution = None
            continue
        corpus_current = matched_docs if focused_mode else documents
        similar_corpus = list(corpus_current) + list(historical_docs)
        similar = retrieve_similar(
            doc,
            similar_corpus,
            top_k=res_cfg.top_k,
            term_matched_only=focused_mode,
        )
        doc_codes = codes_for_document(doc, focused_error_code=focused_error_code)
        if index_history and primary_code and primary_code in doc_codes:
            history = index_history
        else:
            history = resolutions_for_codes(doc_codes, kdir=kdir, cfg=cfg) if doc_codes else []
        doc.resolution = suggest_resolution(
            doc,
            findings_by_key=findings_by_key,
            similar=similar,
            cfg=res_cfg,
            include_similar_documents=focused_mode,
            focused_error_code=focused_error_code or primary_code,
            historical_resolutions=history,
            aggregated_resolution=aggregated if focused_mode and primary_code else None,
            index_document_summaries=index_entry.get("document_summaries") or []
            if focused_mode
            else [],
            accepted_evidence=accepted_ev if focused_mode and primary_code else None,
            confirmed_resolution=confirmed_res if focused_mode and primary_code else None,
            documents_by_id=documents_by_id,
        )

    finding_resolutions: list[ResolutionSuggestion] = []
    if accepted_resolution is not None:
        finding_resolutions.append(accepted_resolution)
    if focused_mode and not matched_docs and rows and accepted_resolution is None:
        fr = build_finding_resolution(
            rows,
            focused_error_code=focused_error_code,
            focused_error_field=focused_error_field,
        )
        if fr:
            finding_resolutions.append(fr)

    return (
        IngestManifest(
            root=docs_root.resolve(),
            documents=documents,
            generated_at=datetime.now(timezone.utc).isoformat(),
        ),
        finding_resolutions,
    )
