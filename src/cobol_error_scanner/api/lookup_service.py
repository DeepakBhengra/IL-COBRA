"""Service helpers for the external scan-and-lookup API."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from cobol_error_scanner.data_access import load_records, records_to_frame
from cobol_error_scanner.document_access import historical_resolution_text
from cobol_error_scanner.mapping_catalog import MAX_ERROR_FIELD_INPUT_LEN, validate_error_field_query
from cobol_error_scanner.scan_service import default_config, optional_path, run_scan


def resolve_lookup_paths(
    *,
    source_root: str = "",
    rules_path: str = "",
    out_dir: str = "",
    corora_mappings: str = "",
) -> dict[str, Path | None]:
    """Resolve request paths, falling back to app defaults."""
    cfg = default_config()

    resolved_out_dir: Path
    if out_dir.strip():
        resolved_out_dir = Path(out_dir).expanduser().resolve()
    else:
        base_out_dir = Path(cfg["out_dir"]).expanduser().resolve()
        resolved_out_dir = base_out_dir / "api-lookups" / uuid4().hex

    return {
        "source_root": Path((source_root or cfg["source_root"]).strip()).expanduser().resolve(),
        "rules_path": Path((rules_path or cfg["rules_path"]).strip()).expanduser().resolve(),
        "out_dir": resolved_out_dir,
        "corora_mappings": optional_path(corora_mappings),
    }


def validate_lookup_query(*, error_code: str = "", error_field: str = "") -> tuple[str, str]:
    """Validate the mutually exclusive focused-scan lookup inputs."""
    normalized_code = error_code.strip().upper()
    normalized_field = error_field.strip()

    if bool(normalized_code) == bool(normalized_field):
        raise ValueError("Provide exactly one of error_code or error_field")

    if normalized_code and len(normalized_code) != 2:
        raise ValueError("error_code must be exactly 2 characters")

    if normalized_field:
        normalized_field = validate_error_field_query(normalized_field)
        normalized_field = normalized_field[:MAX_ERROR_FIELD_INPUT_LEN]

    return normalized_code, normalized_field


def build_lookup_response(
    *,
    error_code: str = "",
    error_field: str = "",
    source_root: str = "",
    rules_path: str = "",
    out_dir: str = "",
    corora_mappings: str = "",
    summarizer: str = "heuristic",
) -> dict[str, object]:
    """Run a focused scan and return all findings for external API consumers."""
    normalized_code, normalized_field = validate_lookup_query(
        error_code=error_code,
        error_field=error_field,
    )
    paths = resolve_lookup_paths(
        source_root=source_root,
        rules_path=rules_path,
        out_dir=out_dir,
        corora_mappings=corora_mappings,
    )
    source_root_path = paths["source_root"]
    rules_path_path = paths["rules_path"]
    out_dir_path = paths["out_dir"]
    corora_mappings_path = paths["corora_mappings"]
    assert isinstance(source_root_path, Path)
    assert isinstance(rules_path_path, Path)
    assert isinstance(out_dir_path, Path)

    out_dir_path.mkdir(parents=True, exist_ok=True)

    program_count, finding_count, _table_name = run_scan(
        source_root_path,
        rules_path_path,
        out_dir_path,
        summarizer,
        error_code=normalized_code,
        error_field=normalized_field,
        corora_mappings=corora_mappings_path,
    )

    records = load_records(out_dir_path / "errors.jsonl")
    frame = records_to_frame(records)
    findings: list[dict[str, object]] = []
    for _, row in frame.iterrows():
        raw = row.to_dict()
        findings.append(
            {
                "error_code": str(raw.get("error_code") or "").strip(),
                "error_field": str(raw.get("error_field") or "").strip(),
                "program": str(raw.get("program") or "").strip(),
                "line": None if raw.get("line") in ("", None) else int(raw.get("line")),
                "paragraph": str(raw.get("paragraph") or "").strip(),
                "condition": str(raw.get("condition") or "").strip(),
                "summary": str(raw.get("row_summary") or "").strip(),
                "historical_resolution": historical_resolution_text(raw, out_dir_path),
            }
        )

    return {
        "query": {"error_code": normalized_code, "error_field": normalized_field},
        "program_count": program_count,
        "finding_count": finding_count,
        "findings": findings,
        "out_dir": str(out_dir_path),
    }
