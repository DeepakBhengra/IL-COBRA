"""Emit searchable documentation (JSON lines + optional HTML index)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cobol_error_scanner.models import ScanManifest


def _md_cell(s: str) -> str:
    t = (s or "").replace("\n", " ").replace("|", "\\|").strip()
    return t or " "


def write_jsonl(manifest: ScanManifest, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in manifest.to_searchable_records():
            f.write(json.dumps(row, default=str) + "\n")


def write_markdown_table(manifest: ScanManifest, out_path: Path) -> None:
    """Write markdown: Error Code | Error field | Program | Line | Paragraph | …."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "| Error Code | Error field | Program | Line | Paragraph | Condition | Parameters | Summary | Mapping detail |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for p in manifest.programs:
        for occ in p.occurrences:
            line_cell = "" if occ.location.line == 0 else str(occ.location.line)
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(occ.code),
                        _md_cell(occ.error_field),
                        _md_cell(p.program_id),
                        _md_cell(line_cell),
                        _md_cell(occ.paragraph or ""),
                        _md_cell(occ.condition),
                        _md_cell(occ.parameters_text),
                        _md_cell(occ.row_summary),
                        _md_cell(occ.mapping_detail),
                    ]
                )
                + " |"
            )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest_json(manifest: ScanManifest, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = manifest.model_dump(mode="json")
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def build_manifest(root: Path, programs: list) -> ScanManifest:
    m = ScanManifest(root=root.resolve(), programs=programs)
    m.generated_at = datetime.now(timezone.utc).isoformat()
    return m
