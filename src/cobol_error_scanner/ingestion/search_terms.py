"""Build search terms from scan results for operational document matching."""

from __future__ import annotations

import re

from cobol_error_scanner.mapping_catalog import MAX_ERROR_FIELD_INPUT_LEN
from cobol_error_scanner.models import ProgramSummary

_FIELD_SUFFIX_RE = re.compile(
    r"(?:CORORA-R-|CORORL-R-|CORORA-|CORORL-)?(ERR(?:OR)?-[A-Z0-9-]+|ERROR-[A-Z0-9-]+)",
    re.IGNORECASE,
)


def field_aliases(full_field: str) -> list[str]:
    """Short names useful in tickets/runbooks (e.g. ERROR-LINE1-NOT-CMNT)."""
    if not full_field.strip():
        return []
    upper = full_field.upper().strip()
    aliases: list[str] = [upper[:MAX_ERROR_FIELD_INPUT_LEN]]
    m = _FIELD_SUFFIX_RE.search(upper)
    if m:
        suffix = m.group(1).upper()
        for alias in (suffix, suffix.replace("ERROR-", "ERR-")):
            if alias and alias not in aliases:
                aliases.append(alias[:MAX_ERROR_FIELD_INPUT_LEN])
    if upper.startswith("CORORL-R-"):
        tail = upper[len("CORORL-R-") :][:MAX_ERROR_FIELD_INPUT_LEN]
        if tail and tail not in aliases:
            aliases.append(tail)
    if upper.startswith("CORORA-R-"):
        tail = upper[len("CORORA-R-") :][:MAX_ERROR_FIELD_INPUT_LEN]
        if tail and tail not in aliases:
            aliases.append(tail)
    return aliases


def collect_search_terms(
    programs: list[ProgramSummary],
    *,
    focused_error_code: str = "",
    focused_error_field: str = "",
) -> dict[str, set[str]]:
    codes: set[str] = set()
    fields: set[str] = set()
    field_aliases_set: set[str] = set()

    if focused_error_code.strip():
        codes.add(focused_error_code.strip().upper())
    if focused_error_field.strip():
        ef = focused_error_field.strip().upper()[:MAX_ERROR_FIELD_INPUT_LEN]
        fields.add(ef)
        field_aliases_set.update(field_aliases(ef))

    for prog in programs:
        for occ in prog.occurrences:
            if occ.code:
                codes.add(occ.code.upper())
            if occ.error_field:
                ef = occ.error_field.upper()
                fields.add(ef)
                field_aliases_set.update(field_aliases(ef))

    return {
        "error_codes": codes,
        "error_fields": fields,
        "field_aliases": field_aliases_set,
    }


def strict_terms_from_focused_scan(
    rows: list[dict],
    *,
    focused_error_code: str = "",
    focused_error_field: str = "",
) -> dict[str, set[str]]:
    """Search terms for document matching after a focused COBOL scan."""
    codes: set[str] = set()
    fields: set[str] = set()
    aliases: set[str] = set()
    if focused_error_code.strip():
        codes.add(focused_error_code.strip().upper())
    if focused_error_field.strip():
        ef = focused_error_field.strip().upper()[:MAX_ERROR_FIELD_INPUT_LEN]
        fields.add(ef)
        aliases.update(field_aliases(ef))
    for row in rows:
        c = str(row.get("error_code", "")).upper()
        if c:
            codes.add(c)
        f = str(row.get("error_field", "")).upper()
        if f:
            fields.add(f)
            aliases.update(field_aliases(f))
    return {"error_codes": codes, "error_fields": fields, "field_aliases": aliases}
