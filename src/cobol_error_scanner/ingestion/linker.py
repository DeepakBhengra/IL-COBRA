"""Link operational documents to COBOL scan findings."""

from __future__ import annotations

import json
from pathlib import Path

from cobol_error_scanner.ingestion.document_search import document_matches_terms
from cobol_error_scanner.ingestion.entity_extract import extract_entities, extract_mentioned_error_codes
from cobol_error_scanner.ingestion.models import DocumentLink, OperationalDocument

StrictTerms = dict[str, set[str]]


def load_finding_rows(errors_jsonl: Path) -> list[dict]:
    if not errors_jsonl.is_file():
        return []
    rows: list[dict] = []
    with errors_jsonl.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _finding_key(row: dict) -> str:
    return "|".join(
        [
            str(row.get("program", "")),
            str(row.get("error_code", "")),
            str(row.get("error_field", "")),
            str(row.get("line", "")),
            str(row.get("paragraph", "")),
        ]
    )


def _mentioned_error_codes(entities: list) -> set[str]:
    """Two-character (or explicit) error codes referenced in document text."""
    return {str(ent.value).upper() for ent in entities if ent.kind == "error_code" and ent.value}


def _index_findings(rows: list[dict]) -> dict[str, list[dict]]:
    by_code: dict[str, list[dict]] = {}
    by_program: dict[str, list[dict]] = {}
    by_field: dict[str, list[dict]] = {}
    for row in rows:
        code = str(row.get("error_code", "")).upper()
        prog = str(row.get("program", "")).upper()
        field = str(row.get("error_field", "")).upper()
        if code:
            by_code.setdefault(code, []).append(row)
        if prog:
            by_program.setdefault(prog, []).append(row)
        if field:
            by_field.setdefault(field, []).append(row)
    return {"code": by_code, "program": by_program, "field": by_field}


def link_document(
    doc: OperationalDocument,
    rows: list[dict],
    *,
    rules_path: Path | None = None,
    strict_terms: StrictTerms | None = None,
) -> OperationalDocument:
    if strict_terms:
        ok, reasons = document_matches_terms(
            doc,
            error_codes=strict_terms.get("error_codes", set()),
            error_fields=strict_terms.get("error_fields", set()),
            field_aliases=strict_terms.get("field_aliases", set()),
        )
        doc.metadata["term_matched"] = ok
        doc.metadata["match_reasons"] = reasons
        if not ok:
            doc.entities = []
            doc.links = []
            return doc

    known_programs = {str(r.get("program", "")).upper() for r in rows if r.get("program")}
    known_codes = {str(r.get("error_code", "")).upper() for r in rows if r.get("error_code")}
    known_fields = {str(r.get("error_field", "")).upper() for r in rows if r.get("error_field")}

    entities = extract_entities(
        doc.body_text,
        known_programs=known_programs if not strict_terms else None,
        known_codes=known_codes,
        known_fields=known_fields,
        rules_path=rules_path,
    )
    doc.entities = entities
    entity_codes = _mentioned_error_codes(entities)
    text_codes = extract_mentioned_error_codes(doc.body_text or "")
    mentioned_codes = entity_codes | text_codes
    doc.metadata["mentioned_error_codes"] = sorted(mentioned_codes)

    if not strict_terms and known_codes:
        _, reasons = document_matches_terms(
            doc,
            error_codes=known_codes,
            error_fields=known_fields,
            field_aliases=set(),
        )
        if reasons:
            doc.metadata["match_reasons"] = reasons

    index = _index_findings(rows)
    links: list[DocumentLink] = []
    matched_keys: set[str] = set()

    for ent in entities:
        candidates: list[dict] = []
        if ent.kind == "error_code":
            candidates = index["code"].get(ent.value.upper(), [])
        elif ent.kind == "program_id":
            # Do not link by program alone — same program can surface many error codes.
            continue
        elif ent.kind == "corora_field":
            val = ent.value.upper()
            for field, field_rows in index["field"].items():
                if val in field or field in val:
                    candidates.extend(field_rows)

        if ent.kind == "corora_field" and mentioned_codes:
            candidates = [
                row
                for row in candidates
                if str(row.get("error_code", "")).upper() in mentioned_codes
            ]

        for row in candidates:
            key = _finding_key(row)
            if key in matched_keys:
                continue
            matched_keys.add(key)
            score = ent.confidence
            if ent.kind == "error_code" and str(row.get("error_code", "")).upper() == ent.value.upper():
                score = min(1.0, score + 0.1)
            links.append(
                DocumentLink(
                    document_id=doc.id,
                    program=str(row.get("program", "")),
                    error_code=str(row.get("error_code", "")),
                    error_field=str(row.get("error_field", "")),
                    score=score,
                    evidence=ent.span or ent.value,
                    finding_key=key,
                )
            )

    doc.links = sorted(links, key=lambda l: -l.score)
    return doc


def link_documents(
    documents: list[OperationalDocument],
    errors_jsonl: Path,
    *,
    rules_path: Path | None = None,
    strict_terms: StrictTerms | None = None,
) -> list[OperationalDocument]:
    rows = load_finding_rows(errors_jsonl)
    return [
        link_document(doc, rows, rules_path=rules_path, strict_terms=strict_terms)
        for doc in documents
    ]
