"""Persistent knowledge store for incremental ingest and cross-run resolution history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cobol_error_scanner.config_loader import AppConfig, load_app_config
from cobol_error_scanner.ingestion.adapters.base import document_id_for
from cobol_error_scanner.ingestion.models import (
    DocumentLink,
    DocumentType,
    EvidenceItem,
    ExtractedEntity,
    OperationalDocument,
    ResolutionSuggestion,
)
from cobol_error_scanner.project_paths import repo_root

INDEX_NAME = "ingest_index.json"
DOCUMENTS_NAME = "documents.jsonl"
RESOLUTIONS_NAME = "resolutions.jsonl"
CODE_FIELD_INDEX_NAME = "code_field_index.json"
EVIDENCE_FEEDBACK_NAME = "evidence_feedback.jsonl"
USER_FIXES_NAME = "user_fixes.jsonl"
CONFIRMED_RESOLUTIONS_NAME = "confirmed_resolutions.jsonl"


def knowledge_dir(cfg: AppConfig | None = None) -> Path:
    app = cfg or load_app_config()
    raw = app.knowledge.dir.strip() or "knowledge/"
    p = Path(raw)
    if not p.is_absolute():
        p = repo_root() / p
    return p.resolve()


def _index_path(kdir: Path) -> Path:
    return kdir / INDEX_NAME


def _documents_path(kdir: Path) -> Path:
    return kdir / DOCUMENTS_NAME


def _resolutions_path(kdir: Path) -> Path:
    return kdir / RESOLUTIONS_NAME


def _code_field_index_path(kdir: Path) -> Path:
    return kdir / CODE_FIELD_INDEX_NAME


def _evidence_feedback_path(kdir: Path) -> Path:
    return kdir / EVIDENCE_FEEDBACK_NAME


def _user_fixes_path(kdir: Path) -> Path:
    return kdir / USER_FIXES_NAME


def _confirmed_resolutions_path(kdir: Path) -> Path:
    return kdir / CONFIRMED_RESOLUTIONS_NAME


def evidence_key(evidence_type: str, document_id: str = "") -> str:
    kind = (evidence_type or "unknown").strip().lower()
    did = (document_id or "").strip()
    return f"{kind}:{did}" if did else kind


def _empty_code_entry() -> dict[str, Any]:
    return {
        "error_fields": [],
        "field_aliases": [],
        "document_ids": [],
        "resolution_keys": [],
        "document_summaries": [],
        "aggregated_resolution": {},
        "accepted_evidence": {},
        "user_fix": {},
        "user_fixes": {},
        "confirmed_resolution": {},
    }


def load_index(kdir: Path | None = None, *, cfg: AppConfig | None = None) -> dict[str, dict[str, Any]]:
    kdir = kdir or knowledge_dir(cfg)
    path = _index_path(kdir)
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def save_index(index: dict[str, dict[str, Any]], kdir: Path | None = None, *, cfg: AppConfig | None = None) -> None:
    kdir = kdir or knowledge_dir(cfg)
    kdir.mkdir(parents=True, exist_ok=True)
    _index_path(kdir).write_text(json.dumps(index, indent=2), encoding="utf-8")


def _file_fingerprint(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {"mtime_ns": st.st_mtime_ns, "size": st.st_size}


def needs_extract(path: Path, index: dict[str, dict[str, Any]] | None = None, *, cfg: AppConfig | None = None) -> bool:
    app = cfg or load_app_config()
    if not app.knowledge.incremental:
        return True
    index = index if index is not None else load_index(cfg=app)
    key = str(path.resolve())
    entry = index.get(key)
    if not entry:
        return True
    try:
        fp = _file_fingerprint(path)
    except OSError:
        return True
    return entry.get("mtime_ns") != fp["mtime_ns"] or entry.get("size") != fp["size"]


def update_index_entry(path: Path, document_id: str, index: dict[str, dict[str, Any]]) -> None:
    key = str(path.resolve())
    entry = _file_fingerprint(path)
    entry["document_id"] = document_id
    index[key] = entry


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")


def load_document_records(kdir: Path | None = None, *, cfg: AppConfig | None = None) -> dict[str, dict[str, Any]]:
    kdir = kdir or knowledge_dir(cfg)
    return {str(r["document_id"]): r for r in _read_jsonl(_documents_path(kdir)) if r.get("document_id")}


def load_resolution_records(kdir: Path | None = None, *, cfg: AppConfig | None = None) -> list[dict[str, Any]]:
    kdir = kdir or knowledge_dir(cfg)
    return _read_jsonl(_resolutions_path(kdir))


def resolution_key(document_id: str, scope: str) -> str:
    return f"{document_id}|{scope}"


def _parse_error_codes(linked_error_codes: str) -> list[str]:
    return [c.strip().upper() for c in (linked_error_codes or "").split(",") if c.strip()]


def _parse_fields(linked_fields: str) -> list[str]:
    return [f.strip().upper() for f in (linked_fields or "").split(",") if f.strip()]


def document_eligible_for_index(row: dict[str, Any]) -> bool:
    """Stricter: require strict term match or COBOL link — not body mention alone."""
    if row.get("term_matched"):
        return True
    if _parse_error_codes(str(row.get("linked_error_codes", ""))):
        return True
    for lnk in row.get("links") or []:
        if isinstance(lnk, dict) and (lnk.get("error_code") or lnk.get("error_field")):
            return True
    return False


def _codes_from_document_row(row: dict[str, Any]) -> set[str]:
    codes = set(_parse_error_codes(str(row.get("linked_error_codes", ""))))
    for lnk in row.get("links") or []:
        if isinstance(lnk, dict) and lnk.get("error_code"):
            codes.add(str(lnk["error_code"]).upper())
    for reason in row.get("match_reasons") or []:
        text = str(reason)
        if text.startswith("error code "):
            codes.add(text.replace("error code ", "", 1).strip().upper())
    return {c for c in codes if c}


def _fields_from_document_row(row: dict[str, Any]) -> set[str]:
    fields = set(_parse_fields(str(row.get("linked_error_fields", ""))))
    for lnk in row.get("links") or []:
        if isinstance(lnk, dict) and lnk.get("error_field"):
            fields.add(str(lnk["error_field"]).upper())
    return {f for f in fields if f}


def _terms_for_error_code(
    code: str,
    *,
    errors_rows: list[dict[str, Any]] | None = None,
) -> tuple[set[str], set[str]]:
    from cobol_error_scanner.ingestion.search_terms import field_aliases

    fields: set[str] = set()
    aliases: set[str] = set()
    cu = code.upper()
    for row in errors_rows or []:
        if str(row.get("error_code", "")).upper() != cu:
            continue
        f = str(row.get("error_field", "")).upper()
        if f:
            fields.add(f)
            aliases.update(field_aliases(f))
    for f in list(fields):
        aliases.update(field_aliases(f))
    return fields, aliases


def load_code_field_index(kdir: Path | None = None, *, cfg: AppConfig | None = None) -> dict[str, Any]:
    kdir = kdir or knowledge_dir(cfg)
    path = _code_field_index_path(kdir)
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def save_code_field_index(index: dict[str, Any], kdir: Path | None = None, *, cfg: AppConfig | None = None) -> None:
    kdir = kdir or knowledge_dir(cfg)
    kdir.mkdir(parents=True, exist_ok=True)
    _code_field_index_path(kdir).write_text(json.dumps(index, indent=2), encoding="utf-8")


def aggregate_resolutions_for_code(
    code: str,
    resolution_rows: list[dict[str, Any]],
    *,
    max_steps: int = 12,
) -> dict[str, Any]:
    cu = code.upper()
    matched = [
        r
        for r in resolution_rows
        if cu in set(r.get("error_codes") or _parse_error_codes(str(r.get("linked_error_codes", ""))))
    ]
    if not matched:
        return {}
    accepted = [r for r in matched if r.get("status") == "accepted"]
    pool = accepted if accepted else matched
    summary = ""
    for row in sorted(pool, key=lambda r: 0 if r.get("status") == "accepted" else 1):
        s = str(row.get("summary", "")).strip()
        if s:
            summary = s
    steps_seen: set[str] = set()
    steps: list[str] = []
    for row in pool:
        for step in row.get("steps") or []:
            st = str(step).strip()
            if not st or st in steps_seen:
                continue
            if st.startswith("Prior resolution") or st.startswith("Knowledge ("):
                continue
            steps_seen.add(st)
            steps.append(st)
    return {
        "summary": summary,
        "steps": steps[:max_steps],
        "resolution_count": len(matched),
    }


def rebuild_code_field_index(
    *,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
    errors_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rebuild code_field_index.json from merged documents and resolutions."""
    app = cfg or load_app_config()
    if not app.knowledge.index_by_code_field:
        return {}
    kdir = kdir or knowledge_dir(app)
    docs = load_document_records(kdir, cfg=app)
    resolutions = load_resolution_records(kdir, cfg=app)
    max_excerpt = app.knowledge.max_indexed_excerpt_chars
    max_steps = app.knowledge.max_aggregated_steps

    index: dict[str, Any] = {}
    all_codes: set[str] = set()

    for row in resolutions:
        all_codes.update(row.get("error_codes") or _parse_error_codes(str(row.get("linked_error_codes", ""))))

    for row in docs.values():
        all_codes.update(_codes_from_document_row(row))

    for row in errors_rows or []:
        c = str(row.get("error_code", "")).upper()
        if c:
            all_codes.add(c)

    old_index = load_code_field_index(kdir, cfg=app)
    for prev_code, prev_entry in old_index.items():
        if not isinstance(prev_entry, dict):
            continue
        if prev_entry.get("user_fix") or prev_entry.get("user_fixes"):
            all_codes.add(str(prev_code).upper())
        if prev_entry.get("confirmed_resolution"):
            all_codes.add(str(prev_code).upper())

    for code in sorted(all_codes):
        if not code:
            continue
        entry = _empty_code_entry()
        prev = old_index.get(code) if isinstance(old_index.get(code), dict) else {}
        if prev.get("accepted_evidence"):
            entry["accepted_evidence"] = dict(prev["accepted_evidence"])
        if prev.get("confirmed_resolution"):
            entry["confirmed_resolution"] = dict(prev["confirmed_resolution"])
        prev_fixes = prev.get("user_fixes")
        if isinstance(prev_fixes, dict) and prev_fixes:
            entry["user_fixes"] = {
                str(k): dict(v) for k, v in prev_fixes.items() if isinstance(v, dict)
            }
        elif prev.get("user_fix"):
            legacy = dict(prev["user_fix"])
            occ_key = finding_occurrence_key(
                str(legacy.get("program", "")),
                legacy.get("line", ""),
            )
            if occ_key and legacy.get("text"):
                entry["user_fixes"] = {occ_key: legacy}
        fields, aliases = _terms_for_error_code(code, errors_rows=errors_rows)
        entry["error_fields"] = sorted(fields)
        entry["field_aliases"] = sorted(aliases)

        doc_ids: set[str] = set()
        summaries: list[dict[str, Any]] = []
        for doc_id, row in docs.items():
            if not document_eligible_for_index(row):
                continue
            row_codes = _codes_from_document_row(row)
            if code not in row_codes:
                continue
            doc_ids.add(doc_id)
            excerpt = (row.get("body_text") or row.get("body_preview") or "")[:max_excerpt]
            summaries.append(
                {
                    "document_id": doc_id,
                    "title": row.get("title", ""),
                    "excerpt": excerpt,
                    "term_matched": bool(row.get("term_matched")),
                    "match_reasons": row.get("match_reasons") or [],
                }
            )

        res_keys: set[str] = set()
        code_resolutions: list[dict[str, Any]] = []
        for row in resolutions:
            row_codes = set(row.get("error_codes") or _parse_error_codes(str(row.get("linked_error_codes", ""))))
            if code not in row_codes:
                continue
            key = row.get("resolution_key") or resolution_key(
                str(row.get("document_id", "")),
                str(row.get("scope", "document")),
            )
            res_keys.add(key)
            code_resolutions.append(row)

        entry["document_ids"] = sorted(doc_ids)
        entry["document_summaries"] = summaries
        entry["resolution_keys"] = sorted(res_keys)
        agg = aggregate_resolutions_for_code(code, code_resolutions, max_steps=max_steps)
        acc = entry.get("accepted_evidence") or {}
        if has_high_confidence_accepted(acc):
            agg = dict(agg)
            acc_steps: list[str] = []
            for item in accepted_evidence_items(acc):
                acc_steps.extend(str(s) for s in item.get("steps") or [])
            if not acc_steps:
                acc_steps = [str(s) for s in acc.get("steps") or []]
            agg_steps = acc_steps + [s for s in agg.get("steps", []) if s not in acc_steps]
            agg["summary"] = str(acc.get("summary", "")) or agg.get("summary", "")
            agg["steps"] = agg_steps[:max_steps]
        entry["aggregated_resolution"] = agg
        has_confirmed = bool(str((entry.get("confirmed_resolution") or {}).get("selected_text", "")).strip())
        if (
            entry["document_ids"]
            or entry["resolution_keys"]
            or entry["aggregated_resolution"]
            or entry.get("user_fixes")
            or entry.get("accepted_evidence")
            or has_confirmed
        ):
            index[code] = entry

    save_code_field_index(index, kdir, cfg=app)
    return index


def lookup_code_field_index(
    error_code: str,
    *,
    focused_error_field: str = "",
    errors_rows: list[dict[str, Any]] | None = None,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> dict[str, Any]:
    """Return index bucket for error_code (fields/aliases merged from scan rows)."""
    app = cfg or load_app_config()
    code = error_code.strip().upper()
    if not code:
        return _empty_code_entry()
    stored = load_code_field_index(kdir, cfg=app).get(code, _empty_code_entry())
    entry = dict(stored)
    scan_fields, scan_aliases = _terms_for_error_code(code, errors_rows=errors_rows)
    if focused_error_field.strip():
        from cobol_error_scanner.ingestion.search_terms import field_aliases
        from cobol_error_scanner.mapping_catalog import MAX_ERROR_FIELD_INPUT_LEN

        ef = focused_error_field.strip().upper()[:MAX_ERROR_FIELD_INPUT_LEN]
        scan_fields.add(ef)
        scan_aliases.update(field_aliases(ef))
    entry["error_fields"] = sorted(set(entry.get("error_fields") or []) | scan_fields)
    entry["field_aliases"] = sorted(set(entry.get("field_aliases") or []) | scan_aliases)
    if "accepted_evidence" not in entry:
        entry["accepted_evidence"] = stored.get("accepted_evidence") or {}
    return entry


def accepted_evidence_items(accepted: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize legacy single-item or multi-item accepted_evidence to a list of items."""
    if not accepted or not isinstance(accepted, dict):
        return []
    raw_items = accepted.get("items")
    if isinstance(raw_items, list) and raw_items:
        return [dict(i) for i in raw_items if isinstance(i, dict)]
    if accepted.get("evidence_index") is not None:
        return [dict(accepted)]
    return []


def get_accepted_evidence(
    error_code: str,
    *,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> dict[str, Any]:
    """Return stored accepted_evidence wrapper (may include ``items`` or legacy flat fields)."""
    code = error_code.strip().upper()
    if not code:
        return {}
    entry = load_code_field_index(kdir, cfg=cfg).get(code, {})
    if isinstance(entry, dict):
        acc = entry.get("accepted_evidence")
        return dict(acc) if isinstance(acc, dict) else {}
    return {}


def get_accepted_evidence_items(
    error_code: str,
    *,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> list[dict[str, Any]]:
    return accepted_evidence_items(get_accepted_evidence(error_code, kdir=kdir, cfg=cfg))


def finding_occurrence_key(program: str, line: Any) -> str:
    """Stable key for one COBOL finding occurrence (program + line)."""
    prog = (program or "").strip().upper()
    ln = _json_safe_line(line)
    if not prog or ln == "":
        return ""
    return f"{prog}:{ln}"


def get_user_fix(
    error_code: str,
    *,
    program: str = "",
    line: Any = "",
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> dict[str, Any]:
    code = error_code.strip().upper()
    occ_key = finding_occurrence_key(program, line)
    if not code or not occ_key:
        return {}
    entry = load_code_field_index(kdir, cfg=cfg).get(code, {})
    if not isinstance(entry, dict):
        return {}
    fixes = entry.get("user_fixes")
    if isinstance(fixes, dict):
        stored = fixes.get(occ_key)
        if isinstance(stored, dict) and stored.get("text"):
            return dict(stored)
    legacy = entry.get("user_fix")
    if isinstance(legacy, dict) and legacy.get("text"):
        if finding_occurrence_key(
            str(legacy.get("program", "")),
            legacy.get("line", ""),
        ) == occ_key:
            return dict(legacy)
    return {}


def list_user_fixes_for_code(
    error_code: str,
    *,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> list[dict[str, Any]]:
    """All saved COBOL Findings fixes for an error code (sorted by program, line)."""
    code = error_code.strip().upper()
    if not code:
        return []
    entry = load_code_field_index(kdir, cfg=cfg).get(code, {})
    if not isinstance(entry, dict):
        return []

    by_key: dict[str, dict[str, Any]] = {}
    fixes = entry.get("user_fixes")
    if isinstance(fixes, dict):
        for occ_key, fix in fixes.items():
            if isinstance(fix, dict) and str(fix.get("text", "")).strip():
                row = dict(fix)
                row.setdefault("occurrence_key", str(occ_key))
                by_key[str(occ_key)] = row

    legacy = entry.get("user_fix")
    if isinstance(legacy, dict) and str(legacy.get("text", "")).strip():
        occ_key = finding_occurrence_key(
            str(legacy.get("program", "")),
            legacy.get("line", ""),
        )
        if occ_key and occ_key not in by_key:
            row = dict(legacy)
            row.setdefault("occurrence_key", occ_key)
            by_key[occ_key] = row

    def _sort_key(item: dict[str, Any]) -> tuple[str, str]:
        return (
            str(item.get("program", "")).upper(),
            str(item.get("line", "")),
        )

    return sorted(by_key.values(), key=_sort_key)


def _json_safe_line(value: Any) -> int | str:
    """Convert pandas/numpy line numbers to JSON-serializable Python scalars."""
    if value is None or value == "":
        return ""
    if hasattr(value, "item") and callable(value.item):
        try:
            value = value.item()
        except (ValueError, TypeError):
            pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value).strip()


def set_user_fix(
    error_code: str,
    fix_text: str,
    *,
    finding_context: dict[str, Any] | None = None,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> dict[str, Any]:
    """Persist a user-reported fix from the COBOL Findings tab."""
    from datetime import datetime, timezone

    app = cfg or load_app_config()
    kdir = kdir or knowledge_dir(app)
    code = error_code.strip().upper()
    text = (fix_text or "").strip()
    if not code:
        raise ValueError("error_code is required")
    if not text:
        raise ValueError("fix text is required")

    ctx = finding_context or {}
    program = str(ctx.get("program", "")).strip()
    safe_line = _json_safe_line(ctx.get("line", ""))
    occ_key = finding_occurrence_key(program, safe_line)
    if not occ_key:
        raise ValueError("program and line are required to save a fix for this finding")

    reviewed_at = datetime.now(timezone.utc).isoformat()
    user_fix: dict[str, Any] = {
        "text": text[:2000],
        "error_code": code,
        "error_field": str(ctx.get("error_field", "")).strip(),
        "program": program,
        "line": safe_line,
        "reviewed_at": reviewed_at,
        "reviewed_by": "dashboard",
    }

    index = load_code_field_index(kdir, cfg=app)
    entry = dict(index.get(code, _empty_code_entry()))
    fixes = dict(entry.get("user_fixes") or {})
    fixes[occ_key] = user_fix
    entry["user_fixes"] = fixes
    entry.pop("user_fix", None)
    entry["error_fields"] = entry.get("error_fields") or []
    entry["field_aliases"] = entry.get("field_aliases") or []
    index[code] = entry
    save_code_field_index(index, kdir, cfg=app)
    rebuild_code_field_index(kdir=kdir, cfg=app)
    _append_user_fix_audit(code, user_fix, kdir=kdir)
    return user_fix


def get_confirmed_resolution(
    error_code: str,
    *,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> dict[str, Any]:
    """Return user-confirmed operational resolution for an error code, if any."""
    code = error_code.strip().upper()
    if not code:
        return {}
    entry = load_code_field_index(kdir, cfg=cfg).get(code, {})
    if not isinstance(entry, dict):
        return {}
    stored = entry.get("confirmed_resolution")
    if isinstance(stored, dict) and str(stored.get("selected_text", "")).strip():
        return dict(stored)
    return {}


def set_confirmed_resolution(
    error_code: str,
    selected_text: str,
    comment: str,
    source: str,
    *,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> dict[str, Any]:
    """Persist analyst-confirmed resolution text for an error code (latest confirm wins)."""
    from datetime import datetime, timezone

    app = cfg or load_app_config()
    kdir = kdir or knowledge_dir(app)
    code = error_code.strip().upper()
    text = (selected_text or "").strip()
    if not code:
        raise ValueError("error_code is required")
    if not text:
        raise ValueError("selected_text is required")
    src = (source or "").strip().lower()
    if src not in ("historical", "condition"):
        raise ValueError("source must be 'historical' or 'condition'")

    reviewed_at = datetime.now(timezone.utc).isoformat()
    confirmed: dict[str, Any] = {
        "selected_text": text[:2000],
        "comment": (comment or "").strip()[:2000],
        "source": src,
        "error_code": code,
        "reviewed_at": reviewed_at,
        "reviewed_by": "enterprise-ui",
    }

    index = load_code_field_index(kdir, cfg=app)
    entry = dict(index.get(code, _empty_code_entry()))
    entry["confirmed_resolution"] = confirmed
    entry["error_fields"] = entry.get("error_fields") or []
    entry["field_aliases"] = entry.get("field_aliases") or []
    index[code] = entry
    save_code_field_index(index, kdir, cfg=app)
    _append_confirmed_resolution_audit(code, confirmed, kdir=kdir)
    return confirmed


def _append_confirmed_resolution_audit(
    error_code: str,
    confirmed: dict[str, Any],
    *,
    kdir: Path,
) -> None:
    kdir.mkdir(parents=True, exist_ok=True)
    row = {"error_code": error_code.strip().upper(), **confirmed}
    path = _confirmed_resolutions_path(kdir)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _append_user_fix_audit(
    error_code: str,
    user_fix: dict[str, Any],
    *,
    kdir: Path,
) -> None:
    kdir.mkdir(parents=True, exist_ok=True)
    row = {"error_code": error_code.strip().upper(), **user_fix}
    path = _user_fixes_path(kdir)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def has_high_confidence_accepted(accepted: dict[str, Any] | None) -> bool:
    if not accepted:
        return False
    items = accepted_evidence_items(accepted)
    if items:
        return str(accepted.get("confidence", "")).lower() == "high" and any(
            item.get("excerpt") or item.get("ref") for item in items
        )
    return str(accepted.get("confidence", "")).lower() == "high" and bool(
        accepted.get("excerpt") or accepted.get("summary")
    )


def skip_resolve_document_ids(
    index_entry: dict[str, Any],
    *,
    cfg: AppConfig | None = None,
) -> set[str]:
    app = cfg or load_app_config()
    if not app.knowledge.skip_doc_scan_when_accepted:
        return set()
    accepted = index_entry.get("accepted_evidence") or {}
    if not has_high_confidence_accepted(accepted):
        return set()
    ids = {str(d) for d in index_entry.get("document_ids") or []}
    for item in accepted_evidence_items(accepted):
        did = str(item.get("document_id", "")).strip()
        if did:
            ids.add(did)
    return ids


def evidence_with_indexes(evidence: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, item in enumerate(evidence, 1):
        if isinstance(item, dict):
            row = dict(item)
        else:
            row = (
                item.model_dump()
                if hasattr(item, "model_dump")
                else {"type": "", "ref": "", "excerpt": str(item)}
            )
        row["index"] = i
        out.append(row)
    return out


def is_cobol_finding_evidence(item: Any) -> bool:
    """True when an evidence row is a linked COBOL scan finding (not operational doc)."""
    if isinstance(item, dict):
        return str(item.get("type", "")).lower() == "cobol_finding"
    if hasattr(item, "type"):
        return str(getattr(item, "type", "")).lower() == "cobol_finding"
    return False


def operational_evidence_for_feedback(evidence: list[Any]) -> list[dict[str, Any]]:
    """Document-backed evidence for Operational docs feedback (preserves original indices)."""
    out: list[dict[str, Any]] = []
    for i, item in enumerate(evidence, 1):
        if is_cobol_finding_evidence(item):
            continue
        if isinstance(item, dict):
            row = dict(item)
        else:
            row = (
                item.model_dump()
                if hasattr(item, "model_dump")
                else {"type": "", "ref": "", "excerpt": str(item)}
            )
        row["index"] = int(row.get("index", i))
        out.append(row)
    return out


def _build_accepted_item(
    evidence_index: int,
    item: dict[str, Any],
    *,
    resolution_row: dict[str, Any],
    doc_id: str,
    reviewed_at: str,
    source_resolution_key: str,
) -> dict[str, Any]:
    item_doc_id = str(item.get("document_id", "")).strip()
    evidence_type = str(item.get("type", ""))
    if item_doc_id:
        evidence_doc_id = item_doc_id
    elif str(resolution_row.get("scope")) == "document":
        evidence_doc_id = doc_id
    else:
        evidence_doc_id = ""
    return {
        "evidence_index": evidence_index,
        "type": evidence_type,
        "ref": str(item.get("ref", "")),
        "excerpt": str(item.get("excerpt", ""))[:500],
        "document_id": evidence_doc_id,
        "resolution_document_id": doc_id,
        "evidence_key": evidence_key(evidence_type, evidence_doc_id),
        "summary": str(resolution_row.get("summary", "")),
        "steps": list(resolution_row.get("steps") or []),
        "confidence": "high",
        "reviewed_at": reviewed_at,
        "reviewed_by": "dashboard",
        "source_resolution_key": source_resolution_key,
    }


def resolution_from_accepted_evidence(
    error_code: str,
    accepted: dict[str, Any],
    *,
    scope: str = "finding",
    item: dict[str, Any] | None = None,
) -> ResolutionSuggestion:
    """Build a resolution from accepted evidence (wrapper with items or legacy single item)."""
    code = error_code.strip().upper()
    items = accepted_evidence_items(accepted)
    if item is not None:
        items = [item]
    elif not items:
        items = [accepted] if accepted.get("evidence_index") is not None else []

    primary = items[0] if items else accepted
    if scope == "finding":
        ref_id = f"finding:{code}"
    else:
        ref_id = str(primary.get("document_id", f"finding:{code}"))

    evidence_list: list[EvidenceItem] = []
    steps: list[str] = []
    for it in items:
        idx = it.get("evidence_index", "?")
        ref = str(it.get("ref", ""))
        excerpt = str(it.get("excerpt", ""))[:300]
        evidence_list.append(
            EvidenceItem(
                type=str(it.get("type", "document")),
                ref=ref,
                excerpt=excerpt,
                document_id=str(it.get("document_id", "")),
            )
        )
        if excerpt:
            steps.append(f"Confirmed evidence #{idx} ({ref}): {excerpt[:220]}")
        else:
            steps.append(f"Confirmed evidence #{idx} ({ref})")

    base_summary = str(accepted.get("summary", "")) or str(primary.get("summary", ""))
    if len(items) > 1:
        indices = ", ".join(f"#{it.get('evidence_index', '?')}" for it in items)
        summary = base_summary or f"Confirmed fix for error code {code} ({indices})."
        if not summary.startswith("Confirmed"):
            summary = f"Confirmed {indices}: {summary}"
    else:
        summary = base_summary or f"Confirmed fix for error code {code}."
        prefix = f"Confirmed evidence #{primary.get('evidence_index', '?')}"
        if not summary.startswith("Confirmed"):
            summary = f"{prefix}: {summary}"

    for it in items:
        for step in it.get("steps") or []:
            st = str(step).strip()
            if st and st not in steps:
                steps.append(st)

    return ResolutionSuggestion(
        document_id=ref_id,
        summary=summary[:500],
        steps=steps[:12],
        confidence="high",
        evidence=evidence_list,
        provider="accepted",
    )


def set_accepted_evidence(
    error_code: str,
    evidence_indices: int | list[int],
    resolution_row: dict[str, Any],
    *,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> dict[str, Any]:
    """Persist user-selected evidence item(s) as the confirmed fix for an error code."""
    from datetime import datetime, timezone

    app = cfg or load_app_config()
    kdir = kdir or knowledge_dir(app)
    code = error_code.strip().upper()
    if not code:
        raise ValueError("error_code is required")

    if isinstance(evidence_indices, int):
        indices = [evidence_indices]
    else:
        indices = sorted({int(i) for i in evidence_indices})
    if not indices:
        raise ValueError("at least one evidence index is required")

    evidence = resolution_row.get("evidence") or []
    for evidence_index in indices:
        if evidence_index < 1 or evidence_index > len(evidence):
            raise ValueError(f"evidence_index must be 1..{len(evidence)}")

    doc_id = str(resolution_row.get("document_id", ""))
    reviewed_at = datetime.now(timezone.utc).isoformat()
    source_resolution_key = resolution_row.get("resolution_key") or resolution_key(
        doc_id,
        str(resolution_row.get("scope", "document")),
    )

    items: list[dict[str, Any]] = []
    for evidence_index in indices:
        raw = evidence[evidence_index - 1]
        if not isinstance(raw, dict):
            raw = (
                raw.model_dump()
                if hasattr(raw, "model_dump")
                else {"type": "", "ref": "", "excerpt": str(raw)}
            )
        if is_cobol_finding_evidence(raw):
            raise ValueError(
                "COBOL finding evidence cannot be saved as operational document feedback; "
                "use the COBOL Findings tab Fix box."
            )
        items.append(
            _build_accepted_item(
                evidence_index,
                raw,
                resolution_row=resolution_row,
                doc_id=doc_id,
                reviewed_at=reviewed_at,
                source_resolution_key=source_resolution_key,
            )
        )

    accepted: dict[str, Any] = {
        "confidence": "high",
        "reviewed_at": reviewed_at,
        "reviewed_by": "dashboard",
        "source_resolution_key": source_resolution_key,
        "summary": str(resolution_row.get("summary", "")),
        "steps": list(resolution_row.get("steps") or []),
        "items": items,
        "evidence_index": indices[0],
        "accepted_evidence_indices": indices,
    }
    if len(items) == 1:
        accepted.update(items[0])

    res_key = source_resolution_key
    rows = load_resolution_records(kdir, cfg=app)
    updated_rows: list[dict[str, Any]] = []
    found = False
    for row in rows:
        key = row.get("resolution_key") or resolution_key(
            str(row.get("document_id", "")),
            str(row.get("scope", "document")),
        )
        if key == res_key:
            row = dict(row)
            row["status"] = "accepted"
            row["accepted_evidence_index"] = indices[0]
            row["accepted_evidence_indices"] = indices
            row["confidence"] = "high"
            found = True
        updated_rows.append(row)
    if not found:
        enriched = enrich_resolution_row(dict(resolution_row), run_generated_at=reviewed_at)
        enriched["status"] = "accepted"
        enriched["accepted_evidence_index"] = indices[0]
        enriched["accepted_evidence_indices"] = indices
        enriched["confidence"] = "high"
        updated_rows.append(enriched)
    _write_jsonl(_resolutions_path(kdir), updated_rows)

    index = load_code_field_index(kdir, cfg=app)
    entry = dict(index.get(code, _empty_code_entry()))
    entry["accepted_evidence"] = accepted
    entry["error_fields"] = entry.get("error_fields") or []
    entry["field_aliases"] = entry.get("field_aliases") or []
    index[code] = entry
    save_code_field_index(index, kdir, cfg=app)
    rebuild_code_field_index(kdir=kdir, cfg=app)
    _append_evidence_feedback(code, accepted, kdir=kdir)
    return accepted


def _append_evidence_feedback(
    error_code: str,
    accepted: dict[str, Any],
    *,
    kdir: Path,
) -> None:
    kdir.mkdir(parents=True, exist_ok=True)
    row = {"error_code": error_code.strip().upper(), **accepted}
    path = _evidence_feedback_path(kdir)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def load_documents_for_index_entry(
    entry: dict[str, Any],
    *,
    exclude_ids: set[str] | None = None,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> list[OperationalDocument]:
    exclude_ids = exclude_ids or set()
    records = load_document_records(kdir, cfg=cfg)
    out: list[OperationalDocument] = []
    for doc_id in entry.get("document_ids") or []:
        if doc_id in exclude_ids:
            continue
        row = records.get(str(doc_id))
        if row is None:
            continue
        out.append(record_to_operational_document(row))
    return out


def load_resolutions_for_index_entry(
    entry: dict[str, Any],
    *,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
    prefer_accepted: bool = True,
) -> list[dict[str, Any]]:
    want = set(entry.get("resolution_keys") or [])
    if not want:
        return []
    rows = load_resolution_records(kdir, cfg=cfg)
    matched = [
        r
        for r in rows
        if (r.get("resolution_key") or resolution_key(
            str(r.get("document_id", "")),
            str(r.get("scope", "document")),
        ))
        in want
    ]
    if prefer_accepted:
        accepted = [r for r in matched if r.get("status") == "accepted"]
        if accepted:
            return accepted
    return matched


def _links_from_record(row: dict[str, Any]) -> list[DocumentLink]:
    raw = row.get("links") or []
    out: list[DocumentLink] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(DocumentLink(**{k: v for k, v in item.items() if k in DocumentLink.model_fields}))
    return out


def record_to_operational_document(row: dict[str, Any]) -> OperationalDocument:
    doc_type = row.get("doc_type", "unknown")
    try:
        dt = DocumentType(doc_type)
    except ValueError:
        dt = DocumentType.unknown
    meta = dict(row.get("metadata") or {})
    if row.get("term_matched") is not None:
        meta["term_matched"] = bool(row.get("term_matched"))
    if row.get("match_reasons"):
        meta["match_reasons"] = row.get("match_reasons")
    meta.setdefault("from_knowledge_store", True)
    return OperationalDocument(
        id=str(row["document_id"]),
        source_path=Path(row.get("source_path", "")),
        doc_type=dt,
        title=str(row.get("title", "")),
        body_text=str(row.get("body_text") or row.get("body_preview") or ""),
        metadata=meta,
        chunks=list(row.get("chunks") or []),
        search_text=str(row.get("search_text", "")),
        ingested_at=str(row.get("ingested_at", "")),
        entities=[ExtractedEntity(**e) for e in row.get("entities") or [] if isinstance(e, dict)],
        links=_links_from_record(row),
    )


def load_operational_document_by_id(
    document_id: str,
    *,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> OperationalDocument | None:
    did = document_id.strip()
    if not did:
        return None
    row = load_document_records(kdir, cfg=cfg).get(did)
    if row is None:
        return None
    return record_to_operational_document(row)


def load_historical_documents(
    *,
    exclude_ids: set[str] | None = None,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> list[OperationalDocument]:
    exclude_ids = exclude_ids or set()
    records = load_document_records(kdir, cfg=cfg)
    out: list[OperationalDocument] = []
    for doc_id, row in records.items():
        if doc_id in exclude_ids:
            continue
        out.append(record_to_operational_document(row))
    return out


def document_record_from_operational(doc: OperationalDocument, *, body_in_store: bool = True) -> dict[str, Any]:
    return {
        "document_id": doc.id,
        "source_path": str(doc.source_path),
        "doc_type": doc.doc_type.value,
        "title": doc.title,
        "body_preview": (doc.body_text or "")[:500],
        "body_text": doc.body_text if body_in_store else "",
        "metadata": doc.metadata,
        "term_matched": doc.metadata.get("term_matched", False),
        "match_reasons": doc.metadata.get("match_reasons", []),
        "entity_count": len(doc.entities),
        "link_count": len(doc.links),
        "linked_programs": ",".join(sorted({lnk.program for lnk in doc.links if lnk.program})),
        "linked_error_codes": ",".join(
            sorted({lnk.error_code for lnk in doc.links if lnk.error_code})
        ),
        "linked_error_fields": ",".join(
            sorted({lnk.error_field for lnk in doc.links if lnk.error_field})
        ),
        "search_text": doc.search_text,
        "ingested_at": doc.ingested_at,
        "links": [lnk.model_dump() for lnk in doc.links],
        "entities": [e.model_dump() for e in doc.entities],
        "chunks": doc.chunks,
    }


def enrich_resolution_row(row: dict[str, Any], *, run_generated_at: str = "") -> dict[str, Any]:
    out = dict(row)
    doc_id = str(out.get("document_id", ""))
    scope = str(out.get("scope", "document"))
    out["resolution_key"] = resolution_key(doc_id, scope)
    codes = _parse_error_codes(str(out.get("linked_error_codes", "")))
    fields = _parse_fields(str(out.get("linked_error_fields", "")))
    if scope == "finding" and doc_id.startswith("finding:"):
        code = doc_id.replace("finding:", "", 1).strip()
        if code.upper().startswith("FIELD:"):
            pass
        elif code:
            codes.append(code.upper())
    out["error_codes"] = sorted(set(codes))
    out["error_fields"] = sorted(set(fields))
    from cobol_error_scanner.ingestion.search_terms import field_aliases

    alias_set: set[str] = set()
    for f in out["error_fields"]:
        alias_set.update(field_aliases(f))
    out["field_aliases"] = sorted(alias_set)
    out.setdefault("status", "proposed")
    out.setdefault("reviewed_at", "")
    out.setdefault("reviewer", "")
    if run_generated_at:
        out["run_generated_at"] = run_generated_at
    return out


def resolutions_for_codes(
    codes: set[str],
    *,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
    prefer_accepted: bool = True,
) -> list[dict[str, Any]]:
    if not codes:
        return []
    want = {c.upper() for c in codes if c}
    rows = load_resolution_records(kdir, cfg=cfg)
    matched: list[dict[str, Any]] = []
    for row in rows:
        row_codes = set(row.get("error_codes") or _parse_error_codes(str(row.get("linked_error_codes", ""))))
        if want & row_codes:
            matched.append(row)
    if prefer_accepted:
        accepted = [r for r in matched if r.get("status") == "accepted"]
        if accepted:
            return accepted
    return matched


def merge_documents(
    run_rows: list[dict[str, Any]],
    *,
    operational_docs: list[OperationalDocument] | None = None,
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> None:
    app = cfg or load_app_config()
    if not app.knowledge.merge_on_write:
        return
    kdir = kdir or knowledge_dir(app)
    existing = load_document_records(kdir, cfg=app)
    index = load_index(kdir, cfg=app)
    by_id = {doc.id: doc for doc in operational_docs or []}
    for row in run_rows:
        doc_id = str(row.get("document_id", ""))
        if not doc_id:
            continue
        if doc_id in by_id:
            stored = document_record_from_operational(by_id[doc_id])
        else:
            stored = dict(row)
            stored.setdefault("body_text", row.get("body_preview", ""))
        existing[doc_id] = stored
        sp = stored.get("source_path")
        if sp:
            try:
                update_index_entry(Path(sp), doc_id, index)
            except OSError:
                pass
    _write_jsonl(_documents_path(kdir), list(existing.values()))
    save_index(index, kdir, cfg=app)


def merge_resolutions(
    run_rows: list[dict[str, Any]],
    *,
    run_generated_at: str = "",
    kdir: Path | None = None,
    cfg: AppConfig | None = None,
) -> None:
    app = cfg or load_app_config()
    if not app.knowledge.merge_on_write:
        return
    kdir = kdir or knowledge_dir(app)
    existing_list = load_resolution_records(kdir, cfg=app)
    by_key: dict[str, dict[str, Any]] = {}
    for row in existing_list:
        key = row.get("resolution_key") or resolution_key(
            str(row.get("document_id", "")),
            str(row.get("scope", "document")),
        )
        by_key[key] = row
    for row in run_rows:
        enriched = enrich_resolution_row(row, run_generated_at=run_generated_at)
        key = enriched["resolution_key"]
        prev = by_key.get(key)
        if prev and prev.get("status") == "accepted":
            enriched["status"] = "accepted"
            enriched["steps"] = prev.get("steps", enriched.get("steps"))
            enriched["summary"] = prev.get("summary", enriched.get("summary"))
            enriched["reviewed_at"] = prev.get("reviewed_at", "")
            enriched["reviewer"] = prev.get("reviewer", "")
        by_key[key] = enriched
    _write_jsonl(_resolutions_path(kdir), list(by_key.values()))


def load_cached_document(path: Path, *, kdir: Path | None = None, cfg: AppConfig | None = None) -> OperationalDocument | None:
    doc_id = document_id_for(path)
    records = load_document_records(kdir, cfg=cfg)
    row = records.get(doc_id)
    if row is None:
        return None
    return record_to_operational_document(row)


def persist_ingest_run(
    manifest_document_rows: list[dict[str, Any]],
    resolution_rows: list[dict[str, Any]],
    *,
    operational_docs: list[OperationalDocument] | None = None,
    run_generated_at: str = "",
    errors_rows: list[dict[str, Any]] | None = None,
    cfg: AppConfig | None = None,
) -> Path:
    """Merge current run artifacts into the knowledge store; return knowledge directory."""
    app = cfg or load_app_config()
    kdir = knowledge_dir(app)
    merge_documents(
        manifest_document_rows,
        operational_docs=operational_docs,
        kdir=kdir,
        cfg=app,
    )
    merge_resolutions(resolution_rows, run_generated_at=run_generated_at, kdir=kdir, cfg=app)
    if app.knowledge.index_by_code_field:
        rebuild_code_field_index(kdir=kdir, cfg=app, errors_rows=errors_rows)
    return kdir


def codes_for_document(doc: OperationalDocument, *, focused_error_code: str = "") -> set[str]:
    codes = {lnk.error_code.upper() for lnk in doc.links if lnk.error_code}
    if focused_error_code.strip():
        codes.add(focused_error_code.strip().upper())
    return codes
