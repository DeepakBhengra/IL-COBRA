"""Load operational document artifacts and match them to COBOL findings."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from cobol_error_scanner.ingestion.document_search import _mentions_code
from cobol_error_scanner.ingestion.linker import _finding_key
from cobol_error_scanner.ingestion.operational_docs_filter import document_row_matches_active_codes
from cobol_error_scanner.ingestion.knowledge_store import get_confirmed_resolution
from cobol_error_scanner.ingestion.resolution import filter_mapping_detail_steps

_EVIDENCE_SNIPPET_RADIUS = 80
_MAX_EVIDENCE_LEN = 240
_MAX_HISTORICAL_RESOLUTION_LEN = 800
_HISTORICAL_SNIPPET_RADIUS = 300


def load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _documents_jsonl_path(out_dir: Path) -> Path:
    primary = out_dir / "documents.jsonl"
    if primary.is_file():
        return primary
    try:
        from cobol_error_scanner.config_loader import load_app_config
        from cobol_error_scanner.ingestion.knowledge_store import knowledge_dir

        kdir = knowledge_dir(cfg=load_app_config())
        fallback = kdir / "documents.jsonl"
        if fallback.is_file():
            return fallback
    except Exception:
        pass
    return primary


def load_documents(out_dir: Path) -> list[dict[str, Any]]:
    return load_jsonl_records(_documents_jsonl_path(out_dir))


def _resolutions_jsonl_path(out_dir: Path) -> Path:
    primary = out_dir / "resolutions.jsonl"
    if primary.is_file():
        return primary
    try:
        from cobol_error_scanner.config_loader import load_app_config
        from cobol_error_scanner.ingestion.knowledge_store import knowledge_dir

        kdir = knowledge_dir(cfg=load_app_config())
        fallback = kdir / "resolutions.jsonl"
        if fallback.is_file():
            return fallback
    except Exception:
        pass
    return primary


def load_resolutions(out_dir: Path) -> list[dict[str, Any]]:
    return load_jsonl_records(_resolutions_jsonl_path(out_dir))


def ingest_status(out_dir: Path) -> dict[str, Any]:
    docs_path = _documents_jsonl_path(out_dir)
    res_path = _resolutions_jsonl_path(out_dir)
    documents = load_documents(out_dir)
    resolutions = load_resolutions(out_dir)
    last_ingested_at = ""
    for doc in documents:
        ts = str(doc.get("ingested_at") or "")
        if ts > last_ingested_at:
            last_ingested_at = ts
    return {
        "has_documents": docs_path.is_file(),
        "has_resolutions": res_path.is_file(),
        "document_count": len(documents),
        "resolution_count": len(resolutions),
        "last_ingested_at": last_ingested_at,
    }


def _split_csv(value: str) -> set[str]:
    return {part.strip().upper() for part in value.split(",") if part.strip()}


def _doc_link_score_for_finding(doc: dict[str, Any], finding_key: str) -> float:
    best = 0.0
    for link in doc.get("links") or []:
        if link.get("finding_key") == finding_key:
            best = max(best, float(link.get("score") or 0))
    return best


def _doc_search_text(doc: dict[str, Any]) -> str:
    parts = [
        str(doc.get("title", "")),
        str(doc.get("body_preview", "")),
        str(doc.get("body_text", "")),
        str(doc.get("search_text", "")),
    ]
    meta = doc.get("metadata") or {}
    if isinstance(meta, dict):
        parts.append(str(meta.get("body_preview", "")))
    return "\n".join(p for p in parts if p)


def _mentioned_codes_in_doc(doc: dict[str, Any]) -> set[str]:
    hay = _doc_search_text(doc)
    meta = doc.get("metadata") or {}
    stored = meta.get("mentioned_error_codes")
    if isinstance(stored, list) and stored:
        return {
            str(c).upper()
            for c in stored
            if c and _mentions_code(hay, str(c).upper())
        }
    mentioned: set[str] = set()
    for entity in doc.get("entities") or []:
        if entity.get("kind") == "error_code" and entity.get("value"):
            cu = str(entity["value"]).upper()
            if _mentions_code(hay, cu):
                mentioned.add(cu)
    return mentioned


def _doc_conflicts_with_finding_code(doc: dict[str, Any], code: str) -> bool:
    """True when the document explicitly names other error codes but not this one."""
    mentioned = _mentioned_codes_in_doc(doc)
    if not mentioned:
        return False
    return code.upper() not in mentioned


def _doc_matches_finding(
    doc: dict[str, Any],
    *,
    finding_key: str,
    error_code: str,
    error_field: str,
    program: str,
) -> tuple[bool, float]:
    code = error_code.upper()
    field = error_field.upper()
    prog = program.upper()
    if not code:
        return False, 0.0

    if _doc_conflicts_with_finding_code(doc, code):
        return False, 0.0

    links = doc.get("links") or []
    best = 0.0
    for link in links:
        link_code = str(link.get("error_code", "")).upper()
        if link_code != code:
            continue
        link_field = str(link.get("error_field", "")).upper()
        link_prog = str(link.get("program", "")).upper()
        if field and link_field and link_field != field:
            continue
        if prog and link_prog and link_prog != prog:
            continue
        score = float(link.get("score") or 0.8)
        if link.get("finding_key") == finding_key:
            score = max(score, 1.0)
        best = max(best, score)

    if best > 0:
        return True, best

    if document_row_matches_active_codes(doc, {code}):
        return True, 0.75

    return False, 0.0


def _resolution_matches_finding(
    res: dict[str, Any],
    *,
    error_code: str,
    error_field: str,
) -> bool:
    if not res.get("summary"):
        return False
    if res.get("scope") != "finding":
        return False

    doc_id = str(res.get("document_id") or "")
    code = error_code.upper()
    field = error_field.upper()
    if doc_id.startswith("finding:field:"):
        id_field = doc_id[len("finding:field:") :].upper()
        return bool(field) and (field.startswith(id_field) or id_field.startswith(field))
    if doc_id.startswith("finding:"):
        id_code = doc_id[len("finding:") :].upper()
        if id_code.startswith("FIELD:"):
            return False
        return bool(code) and code == id_code

    codes = _split_csv(str(res.get("linked_error_codes") or ""))
    fields = _split_csv(str(res.get("linked_error_fields") or ""))
    if code and codes and code not in codes:
        return False
    if field and fields and field not in fields:
        return False
    return True


def _resolution_codes(res: dict[str, Any]) -> set[str]:
    codes = _split_csv(str(res.get("linked_error_codes") or ""))
    for raw in res.get("error_codes") or []:
        if raw:
            codes.add(str(raw).upper())
    return codes


def _document_resolution_matches_code(res: dict[str, Any], error_code: str) -> bool:
    if res.get("scope") != "document" or not res.get("summary"):
        return False
    code = error_code.strip().upper()
    if not code:
        return True
    codes = _resolution_codes(res)
    return not codes or code in codes


def _index_document_resolutions(resolutions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for res in resolutions:
        doc_id = str(res.get("document_id") or "").strip()
        if not doc_id or not _document_resolution_matches_code(res, ""):
            continue
        existing = by_id.get(doc_id)
        if existing is None or (res.get("summary") and not existing.get("summary")):
            by_id[doc_id] = res
    return by_id


def _lookup_document_resolution(
    doc_id: str,
    *,
    error_code: str,
    resolutions_by_doc: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    res = resolutions_by_doc.get(doc_id)
    if res is None:
        return None
    if not _document_resolution_matches_code(res, error_code):
        return None
    return res


def _normalize_ws(text: str) -> str:
    return " ".join(text.split())


def _text_evidence_snippet(
    doc: dict[str, Any],
    error_code: str,
    *,
    radius: int = _EVIDENCE_SNIPPET_RADIUS,
    max_len: int = _MAX_EVIDENCE_LEN,
) -> str:
    """Best-effort excerpt when no formal COBOL link evidence exists."""
    code = error_code.strip().upper()
    if not code:
        return ""
    hay = _doc_search_text(doc)
    if not _mentions_code(hay, code):
        return ""

    idx = hay.upper().find(code)
    if idx >= 0:
        start = max(0, idx - radius)
        end = min(len(hay), idx + len(code) + radius)
        snippet = hay[start:end].replace("\n", " ").strip()
        if snippet:
            return snippet[:max_len]

    pattern = re.compile(
        rf".{{0,{radius}}}error\s*(?:code)?\s*[:=]?\s*{re.escape(code)}.{{0,{radius}}}",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(hay)
    if match:
        return match.group(0).replace("\n", " ").strip()[:max_len]

    preview = str(doc.get("body_preview") or "").strip()
    return preview[:max_len] if preview else ""


def _historical_resolution_excerpt(doc: dict[str, Any], error_code: str) -> str:
    """Full operational excerpt for analyst review (not a tight link-match snippet)."""
    code = error_code.strip().upper()
    if not code:
        return ""

    body = str(doc.get("body_text") or doc.get("body_preview") or "").strip()
    if not body or not _mentions_code(body, code):
        return _text_evidence_snippet(
            doc,
            code,
            radius=_HISTORICAL_SNIPPET_RADIUS,
            max_len=_MAX_HISTORICAL_RESOLUTION_LEN,
        )

    compact = _normalize_ws(body)
    if len(compact) <= _MAX_HISTORICAL_RESOLUTION_LEN:
        return compact

    lines = [ln.strip() for ln in body.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not lines:
        return _text_evidence_snippet(
            doc,
            code,
            radius=_HISTORICAL_SNIPPET_RADIUS,
            max_len=_MAX_HISTORICAL_RESOLUTION_LEN,
        )

    hit_indices = [
        i
        for i, ln in enumerate(lines)
        if code.upper() in ln.upper()
        or re.search(
            rf"\berror\s*(?:code)?\s*[:=]?\s*{re.escape(code)}\b",
            ln,
            re.IGNORECASE,
        )
    ]
    if hit_indices:
        start = hit_indices[0]
        if start > 0 and (lines[start - 1].startswith("#") or len(lines[start - 1]) < 80):
            start -= 1
        end = hit_indices[-1]
        if end + 1 < len(lines):
            end += 1
        excerpt = _normalize_ws("\n".join(lines[start : end + 1]))
        return excerpt[:_MAX_HISTORICAL_RESOLUTION_LEN]

    return _text_evidence_snippet(
        doc,
        code,
        radius=_HISTORICAL_SNIPPET_RADIUS,
        max_len=_MAX_HISTORICAL_RESOLUTION_LEN,
    )


def _expand_confirmed_resolution(
    confirmed: dict[str, Any],
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Upgrade truncated historical confirms when a fuller excerpt is available."""
    if not confirmed or str(confirmed.get("source", "")).lower() != "historical":
        return confirmed
    selected = str(confirmed.get("selected_text", "")).strip()
    if not selected:
        return confirmed
    for doc in documents:
        historical = str(doc.get("historical_resolution") or doc.get("link_evidence") or "").strip()
        if historical.startswith(selected) and len(historical) > len(selected):
            return {**confirmed, "selected_text": historical}
    return confirmed


def _link_evidence_for_finding(
    doc: dict[str, Any],
    *,
    finding_key: str,
    error_code: str,
    error_field: str,
    program: str,
) -> str:
    code = error_code.upper()
    field = error_field.upper()
    prog = program.upper()

    for link in doc.get("links") or []:
        if link.get("finding_key") == finding_key:
            evidence = str(link.get("evidence") or "").strip()
            if evidence:
                return evidence

    best = ""
    best_score = -1.0
    for link in doc.get("links") or []:
        if str(link.get("error_code", "")).upper() != code:
            continue
        link_field = str(link.get("error_field", "")).upper()
        link_prog = str(link.get("program", "")).upper()
        if field and link_field and link_field != field:
            continue
        if prog and link_prog and link_prog != prog:
            continue
        evidence = str(link.get("evidence") or "").strip()
        if not evidence:
            continue
        score = float(link.get("score") or 0.0)
        if link.get("finding_key") == finding_key:
            score = max(score, 1.0)
        if score > best_score:
            best_score = score
            best = evidence
    if best:
        return best

    return _text_evidence_snippet(doc, error_code)


def _technical_resolution_from_finding(row: dict[str, Any]) -> dict[str, Any]:
    """Structured COBOL finding fields for Technical Resolution (non-empty only)."""
    out: dict[str, Any] = {}
    scalar_fields = (
        ("program", "program"),
        ("error_code", "error_code"),
        ("error_field", "error_field"),
        ("line", "line"),
        ("paragraph", "paragraph"),
        ("section", "section"),
        ("statement", "statement"),
        ("condition", "condition"),
        ("row_summary", "row_summary"),
        ("logic_context", "logic_context"),
        ("mapping_detail", "mapping_detail"),
        ("error_message", "error_message"),
    )
    for src_key, dest_key in scalar_fields:
        val = row.get(src_key)
        if val is None:
            continue
        if isinstance(val, (int, float)) and val != 0:
            out[dest_key] = val
        elif isinstance(val, str) and val.strip():
            out[dest_key] = val.strip()
        elif val and not isinstance(val, str):
            out[dest_key] = val

    file_path = str(row.get("file") or "").strip()
    if file_path:
        out["file"] = Path(file_path).name

    related = row.get("related")
    if isinstance(related, list) and related:
        cleaned: list[dict[str, str]] = []
        for item in related:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            entry: dict[str, str] = {"name": name}
            role = str(item.get("role") or "").strip()
            if role:
                entry["role"] = role
            cleaned.append(entry)
        if cleaned:
            out["related"] = cleaned

    return out


def _enrich_matched_document(
    doc: dict[str, Any],
    *,
    score: float,
    finding_key: str,
    error_code: str,
    error_field: str,
    program: str,
    finding_row: dict[str, Any],
    resolutions_by_doc: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    link_evidence = _link_evidence_for_finding(
        doc,
        finding_key=finding_key,
        error_code=error_code,
        error_field=error_field,
        program=program,
    )

    resolution_summary = str(doc.get("resolution_summary") or "").strip()
    resolution_steps = filter_mapping_detail_steps(list(doc.get("resolution_steps") or []))
    resolution_confidence = str(doc.get("resolution_confidence") or "")

    if not resolution_summary:
        doc_id = str(doc.get("document_id") or "")
        stored = _lookup_document_resolution(
            doc_id,
            error_code=error_code,
            resolutions_by_doc=resolutions_by_doc,
        )
        if stored:
            resolution_summary = str(stored.get("summary") or "").strip()
            if not resolution_steps:
                resolution_steps = list(stored.get("steps") or [])
            if not resolution_confidence:
                resolution_confidence = str(stored.get("confidence") or "")

    historical_resolution = _historical_resolution_excerpt(doc, error_code) or link_evidence
    technical_resolution = _technical_resolution_from_finding(finding_row)

    return {
        "document_id": doc.get("document_id", ""),
        "source_path": doc.get("source_path", ""),
        "doc_type": doc.get("doc_type", "unknown"),
        "title": doc.get("title", ""),
        "body_preview": doc.get("body_preview", ""),
        "link_score": score,
        "link_evidence": link_evidence,
        "historical_resolution": historical_resolution,
        "technical_resolution": technical_resolution,
        "resolution_summary": resolution_summary,
        "resolution_steps": resolution_steps,
        "resolution_confidence": resolution_confidence,
        "ingested_at": doc.get("ingested_at", ""),
    }


def _rollup_from_documents(docs: list[dict[str, Any]]) -> dict[str, Any]:
    summaries: list[str] = []
    steps: list[str] = []
    seen_steps: set[str] = set()
    confidence = "low"

    for doc in docs:
        summary = str(doc.get("resolution_summary") or "").strip()
        if summary:
            summaries.append(summary)
        conf = str(doc.get("resolution_confidence") or "")
        if conf == "high":
            confidence = "high"
        elif conf == "medium" and confidence != "high":
            confidence = "medium"
        for step in doc.get("resolution_steps") or []:
            step_text = str(step).strip()
            if step_text and step_text not in seen_steps:
                seen_steps.add(step_text)
                steps.append(step_text)

    summary_text = summaries[0] if len(summaries) == 1 else ""
    if not summary_text and summaries:
        summary_text = f"Based on {len(summaries)} operational document(s): {summaries[0]}"
    if not summary_text and docs:
        titles = [str(d.get("title") or d.get("document_id") or "document") for d in docs[:3]]
        summary_text = f"Review operational document(s): {', '.join(titles)}."

    return {
        "summary": summary_text,
        "steps": filter_mapping_detail_steps(steps)[:8],
        "confidence": confidence,
        "provider": docs[0].get("resolution_provider", "heuristic") if docs else "heuristic",
    }


def get_operational_docs_for_finding(row: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """Return linked documents and aggregated resolution for a COBOL finding row."""
    status = ingest_status(out_dir)
    finding_key = _finding_key(row)
    error_code = str(row.get("error_code") or "")
    error_field = str(row.get("error_field") or "")
    program = str(row.get("program") or "")

    confirmed = get_confirmed_resolution(error_code) if error_code else {}

    if not status["has_documents"]:
        return {
            "has_artifacts": False,
            "finding_key": finding_key,
            "documents": [],
            "summary": "",
            "steps": [],
            "confidence": "",
            "provider": "",
            "document_count": 0,
            "last_ingested_at": status["last_ingested_at"],
            "confirmed_resolution": confirmed,
        }

    all_docs = load_documents(out_dir)
    matched: list[tuple[float, dict[str, Any]]] = []
    for doc in all_docs:
        ok, score = _doc_matches_finding(
            doc,
            finding_key=finding_key,
            error_code=error_code,
            error_field=error_field,
            program=program,
        )
        if ok:
            matched.append((score, doc))

    matched.sort(key=lambda item: -item[0])
    resolutions = load_resolutions(out_dir)
    resolutions_by_doc = _index_document_resolutions(resolutions)

    documents: list[dict[str, Any]] = []
    for score, doc in matched:
        documents.append(
            _enrich_matched_document(
                doc,
                score=score,
                finding_key=finding_key,
                error_code=error_code,
                error_field=error_field,
                program=program,
                finding_row=row,
                resolutions_by_doc=resolutions_by_doc,
            )
        )

    finding_resolution = next(
        (
            res
            for res in resolutions
            if _resolution_matches_finding(
                res, error_code=error_code, error_field=error_field
            )
        ),
        None,
    )

    if finding_resolution:
        summary = str(finding_resolution.get("summary") or "")
        steps = list(finding_resolution.get("steps") or [])
        confidence = str(finding_resolution.get("confidence") or "medium")
        provider = str(finding_resolution.get("provider") or "heuristic")
    elif documents:
        rolled = _rollup_from_documents(documents)
        summary = rolled["summary"]
        steps = rolled["steps"]
        confidence = rolled["confidence"]
        provider = rolled["provider"]
    else:
        summary = ""
        steps = []
        confidence = ""
        provider = ""

    confirmed = _expand_confirmed_resolution(confirmed, documents)

    return {
        "has_artifacts": True,
        "finding_key": finding_key,
        "documents": documents,
        "summary": summary,
        "steps": steps,
        "confidence": confidence,
        "provider": provider,
        "document_count": len(documents),
        "last_ingested_at": status["last_ingested_at"],
        "confirmed_resolution": confirmed,
    }


def historical_resolution_text(row: dict[str, Any], out_dir: Path) -> str:
    """Best single historical-resolution string for API consumers."""
    operational = get_operational_docs_for_finding(row, out_dir)

    confirmed = operational.get("confirmed_resolution") or {}
    if str(confirmed.get("source") or "").lower() == "historical":
        selected = str(confirmed.get("selected_text") or "").strip()
        if selected:
            return selected

    for doc in operational.get("documents") or []:
        historical = str(doc.get("historical_resolution") or doc.get("link_evidence") or "").strip()
        if historical:
            return historical

    summary = str(operational.get("summary") or "").strip()
    if summary:
        return summary

    return ""
