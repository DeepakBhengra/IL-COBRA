"""Export ingestion manifests to JSONL and markdown."""

from __future__ import annotations

import json
from pathlib import Path

from cobol_error_scanner.ingestion.models import IngestManifest, ResolutionSuggestion


def _md_cell(s: str) -> str:
    t = (s or "").replace("\n", " ").replace("|", "\\|").strip()
    return t or " "


def write_documents_jsonl(
    manifest: IngestManifest,
    out_path: Path,
    *,
    focused_scan: bool = False,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in manifest.to_document_records(focused_scan=focused_scan):
            f.write(json.dumps(row, default=str) + "\n")


def write_resolutions_jsonl(
    manifest: IngestManifest,
    out_path: Path,
    *,
    focused_scan: bool = False,
    finding_resolutions: list[ResolutionSuggestion] | None = None,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in manifest.to_resolution_records(
            focused_scan=focused_scan,
            finding_resolutions=finding_resolutions,
        ):
            f.write(json.dumps(row, default=str) + "\n")


def write_documents_table(manifest: IngestManifest, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "| Document | Type | Title | Links | Codes | Summary |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for doc in manifest.documents:
        res_summary = doc.resolution.summary if doc.resolution else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(doc.id),
                    _md_cell(doc.doc_type.value),
                    _md_cell(doc.title),
                    _md_cell(str(len(doc.links))),
                    _md_cell(
                        ", ".join(sorted({lnk.error_code for lnk in doc.links if lnk.error_code}))
                    ),
                    _md_cell(res_summary[:120]),
                ]
            )
            + " |"
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
