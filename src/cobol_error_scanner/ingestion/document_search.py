"""Search operational documents for error codes and field names."""

from __future__ import annotations

import re
from pathlib import Path

from cobol_error_scanner.ingestion.adapters import extract_document
from cobol_error_scanner.ingestion.models import OperationalDocument
from cobol_error_scanner.ingestion.scanner import iter_document_files

_TWO_CHAR_CODE_BOUNDARY = re.compile(
    r"(?<![A-Z0-9])([A-Z0-9]{2})(?![A-Z0-9])",
    re.IGNORECASE,
)


def _mentions_code(text: str, code: str) -> bool:
    if len(code) != 2:
        return code.upper() in text.upper()
    cu = code.upper()
    if re.search(
        rf"(?<![A-Za-z0-9]){re.escape(cu)}(?![A-Za-z0-9])",
        text,
    ):
        return True
    if re.search(
        rf"\berror\s*(?:code)?\s*[:=]?\s*{re.escape(cu)}\b",
        text,
        re.IGNORECASE,
    ):
        return True
    if re.search(rf"['\"]{re.escape(cu)}['\"]", text, re.IGNORECASE):
        return True
    return False


def _mentions_field(text: str, needle: str) -> bool:
    if not needle:
        return False
    return needle.upper() in text.upper()


def document_matches_terms(
    doc: OperationalDocument,
    *,
    error_codes: set[str],
    error_fields: set[str],
    field_aliases: set[str],
) -> tuple[bool, list[str]]:
    """Return (matched, list of human-readable match reasons)."""
    text = f"{doc.title}\n{doc.body_text}"
    reasons: list[str] = []
    for code in sorted(error_codes):
        if _mentions_code(text, code):
            reasons.append(f"error code {code}")
    for field in sorted(error_fields):
        if _mentions_field(text, field):
            reasons.append(f"field {field}")
    for alias in sorted(field_aliases):
        if alias not in error_fields and _mentions_field(text, alias):
            reasons.append(f"field alias {alias}")
    return (bool(reasons), reasons)


def find_matching_documents(
    docs_root: Path,
    *,
    error_codes: set[str],
    error_fields: set[str],
    field_aliases: set[str],
) -> list[tuple[OperationalDocument, list[str]]]:
    matches: list[tuple[OperationalDocument, list[str]]] = []
    for path in iter_document_files(docs_root):
        try:
            doc = extract_document(path)
        except Exception:
            continue
        ok, reasons = document_matches_terms(
            doc,
            error_codes=error_codes,
            error_fields=error_fields,
            field_aliases=field_aliases,
        )
        if ok:
            matches.append((doc, reasons))
    return matches


def _excerpt_for_term(text: str, term: str, radius: int = 120) -> str:
    idx = text.upper().find(term.upper())
    if idx < 0 and len(term) == 2:
        for m in _TWO_CHAR_CODE_BOUNDARY.finditer(text):
            if m.group(1).upper() == term.upper():
                idx = m.start()
                term = m.group(0)
                break
    if idx < 0:
        return (text or "")[:240].strip()
    start = max(0, idx - radius)
    end = min(len(text), idx + len(term) + radius)
    snippet = text[start:end].replace("\n", " ")
    return snippet.strip()


def summarize_document_matches(
    matches: list[tuple[OperationalDocument, list[str]]],
    *,
    error_codes: set[str],
    error_fields: set[str],
    field_aliases: set[str],
) -> str:
    if not matches:
        codes = ", ".join(sorted(error_codes)) or "—"
        fields = ", ".join(sorted(error_fields | field_aliases)) or "—"
        return (
            f"No references found in sample documents for error code(s) [{codes}] "
            f"or field(s) [{fields}]."
        )

    parts: list[str] = []
    for doc, reasons in matches[:8]:
        needles: list[str] = []
        needles.extend(sorted(error_codes))
        needles.extend(sorted(error_fields | field_aliases))
        excerpt = ""
        for needle in needles:
            excerpt = _excerpt_for_term(doc.body_text, needle)
            if excerpt and needle.upper() in excerpt.upper():
                break
        if not excerpt:
            excerpt = (doc.body_text or "")[:240]
        reason_txt = ", ".join(reasons)
        parts.append(
            f"• [{doc.doc_type.value}] {doc.title} ({reason_txt}): {excerpt}"
        )
    if len(matches) > 8:
        parts.append(f"• … and {len(matches) - 8} more document(s).")
    return "\n".join(parts)
