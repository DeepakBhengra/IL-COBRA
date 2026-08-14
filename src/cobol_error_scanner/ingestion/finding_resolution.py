"""COBOL-only resolution when no operational documents match focused terms."""

from __future__ import annotations

from cobol_error_scanner.ingestion.models import EvidenceItem, ResolutionSuggestion

INSIDELINE_NO_OPS_DOCS_MESSAGE = (
    "Please contact Insideline Team with extracted error logs and request curls for analysing "
    "this error code."
)


def insideline_no_ops_docs_message(error_code: str = "") -> str:
    """Guidance when no operational documents are linked to an error code."""
    code = error_code.strip().upper()
    if code:
        return (
            "Please contact Insideline Team with extracted error logs and request curls for "
            f"analysing error code {code}."
        )
    return INSIDELINE_NO_OPS_DOCS_MESSAGE


def _condition_location_suffix(row: dict) -> str:
    """Line/paragraph label for a single COBOL occurrence."""
    line = row.get("line", "")
    para = str(row.get("paragraph", "")).strip()
    if line in (None, "", 0):
        return ""
    loc = f" at line {line}"
    if para:
        loc += f", paragraph {para}"
    return loc


def build_finding_resolution(
    rows: list[dict],
    *,
    focused_error_code: str = "",
    focused_error_field: str = "",
) -> ResolutionSuggestion | None:
    if not rows:
        return None

    code = focused_error_code.strip().upper() or str(rows[0].get("error_code", "")).upper()
    field = focused_error_field.strip() or str(rows[0].get("error_field", "")).strip()
    ref_id = f"finding:{code}" if code else f"finding:field:{field[:30]}"

    evidence: list[EvidenceItem] = []
    steps: list[str] = []
    progs = sorted({str(r.get("program", "")) for r in rows if r.get("program")})

    for row in rows[:10]:
        prog = row.get("program", "")
        ec = row.get("error_code", "")
        excerpt = (
            row.get("row_summary")
            or row.get("condition")
            or row.get("mapping_detail")
            or row.get("statement", "")
        )
        evidence.append(
            EvidenceItem(
                type="cobol_finding",
                ref=f"{prog}:{ec}",
                excerpt=str(excerpt)[:300],
            )
        )

    row0 = rows[0]
    steps.append(
        f"Review COBOL program(s) {', '.join(progs)} for error code {code or '—'}."
    )
    if field:
        steps.append(f"Mapped error field: {field}.")
    cond = str(row0.get("condition", "")).strip()
    if cond:
        loc = _condition_location_suffix(row0) if len(rows) == 1 else ""
        steps.append(f"Validate condition{loc}: {cond[:200]}.")
    mapping = str(row0.get("mapping_detail", "")).strip()
    if mapping:
        steps.append(f"Mapping: {mapping[:200]}.")
    if len(rows) > 1:
        steps.append(f"Review all {len(rows)} COBOL occurrence(s) in the findings table.")

    summary = (
        f"Address {code} in {progs[0]}"
        if code and progs
        else f"Address error field {field} from COBOL scan"
    )
    summary += " (no matching operational documents)."
    steps.append(insideline_no_ops_docs_message(code))

    return ResolutionSuggestion(
        document_id=ref_id,
        summary=summary,
        steps=steps[:8],
        confidence="high" if rows else "medium",
        evidence=evidence,
        provider="heuristic",
    )
