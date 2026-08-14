"""Filter operational document rows by active error code(s) for the current scan."""

from __future__ import annotations

from typing import Any, Iterable

from cobol_error_scanner.ingestion.document_search import _mentions_code


def _row_term_matched(row: dict[str, Any]) -> bool:
    if row.get("term_matched") is True:
        return True
    meta = row.get("metadata")
    if isinstance(meta, dict) and meta.get("term_matched") is True:
        return True
    return False


def _row_search_text(row: dict[str, Any]) -> str:
    parts: list[str] = [
        str(row.get("title", "")),
        str(row.get("body_preview", "")),
        str(row.get("body_text", "")),
        str(row.get("search_text", "")),
    ]
    meta = row.get("metadata")
    if isinstance(meta, dict):
        parts.append(str(meta.get("body_preview", "")))
    return "\n".join(p for p in parts if p)


def _row_text_mentions_code(row: dict[str, Any], code: str) -> bool:
    return _mentions_code(_row_search_text(row), code.strip().upper())


def active_operational_error_codes(
    *,
    finding_codes: Iterable[str] | None = None,
    focused_error_code: str = "",
) -> set[str]:
    """Codes used to scope the Operational docs tab to the current run."""
    codes = {(c or "").strip().upper() for c in (finding_codes or []) if (c or "").strip()}
    fc = (focused_error_code or "").strip().upper()
    if fc and len(fc) == 2:
        codes.add(fc)
    return codes


def document_row_matches_active_codes(row: dict[str, Any], codes: set[str]) -> bool:
    """
    True when the document is relevant to an active error code.

    Prefer COBOL links (linked_error_codes), then persisted match_reasons, then
    title/body text mention of the code.
    """
    if not codes:
        return True

    linked = str(row.get("linked_error_codes", "")).upper()
    linked_codes = {p.strip() for p in linked.split(",") if p.strip()}
    if codes & linked_codes:
        return True

    reasons = row.get("match_reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    if not reasons and isinstance(row.get("metadata"), dict):
        meta_reasons = row["metadata"].get("match_reasons")
        if isinstance(meta_reasons, list):
            reasons = meta_reasons
    for code in codes:
        needle = f"error code {code}".lower()
        for reason in reasons:
            if needle in str(reason).lower():
                return True

    if _row_term_matched(row):
        for code in codes:
            if _row_text_mentions_code(row, code):
                return True

    meta = row.get("metadata") or {}
    stored = meta.get("mentioned_error_codes")
    if isinstance(stored, list):
        stored_codes = {str(c).upper() for c in stored if c}
        if codes & stored_codes:
            for code in codes & stored_codes:
                if _row_text_mentions_code(row, code):
                    return True

    for code in codes:
        if _row_text_mentions_code(row, code):
            return True
    return False


def filter_document_rows_for_codes(
    rows: list[dict[str, Any]],
    codes: set[str],
) -> list[dict[str, Any]]:
    """Return rows that match any active code (or all rows if codes is empty)."""
    if not codes:
        return list(rows)
    return [r for r in rows if document_row_matches_active_codes(r, codes)]
