"""Run operational document ingestion and write output artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from cobol_error_scanner.config_loader import load_app_config
from cobol_error_scanner.llm_client import LLM_PROVIDERS
from cobol_error_scanner.ingestion.docgen import (
    write_documents_jsonl,
    write_documents_table,
    write_resolutions_jsonl,
)
from cobol_error_scanner.ingestion.knowledge_store import persist_ingest_run
from cobol_error_scanner.ingestion.pipeline import ingest_root
from cobol_error_scanner.project_paths import resolve_rules_path


def run_ingest(
    docs_root: Path,
    out_dir: Path,
    *,
    rules_path: Path | None = None,
    resolver: str = "heuristic",
    error_code: str = "",
    error_field: str = "",
    redact: bool = False,
) -> dict[str, int]:
    """Ingest operational documents and link them to COBOL scan findings."""
    docs_root = docs_root.resolve()
    out_dir = out_dir.resolve()
    errors_path = out_dir / "errors.jsonl"
    if not errors_path.is_file():
        raise ValueError(f"Missing {errors_path}. Run a COBOL scan first to produce errors.jsonl.")

    if not docs_root.is_dir():
        raise ValueError(f"Documents folder not found: {docs_root}")

    rules = resolve_rules_path(rules_path) if rules_path else resolve_rules_path(Path("config/error_rules.json"))
    app_cfg = load_app_config()
    if resolver in LLM_PROVIDERS:
        app_cfg.resolver.provider = resolver

    manifest, finding_resolutions = ingest_root(
        docs_root,
        scan_out=out_dir,
        rules_path=rules,
        resolver=resolver,
        redact=redact,
        app_config=app_cfg,
        focused_error_code=error_code,
        focused_error_field=error_field,
    )

    write_documents_jsonl(manifest, out_dir / "documents.jsonl")
    write_resolutions_jsonl(
        manifest,
        out_dir / "resolutions.jsonl",
        finding_resolutions=finding_resolutions,
    )
    write_documents_table(manifest, out_dir / "documents_table.md")

    if app_cfg.knowledge.merge_on_write:
        errors_rows: list[dict] = []
        with errors_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    errors_rows.append(json.loads(line))
        persist_ingest_run(
            manifest.to_document_records(focused_scan=False),
            manifest.to_resolution_records(finding_resolutions=finding_resolutions),
            operational_docs=manifest.documents,
            run_generated_at=manifest.generated_at,
            errors_rows=errors_rows,
            cfg=app_cfg,
        )

    linked = sum(1 for doc in manifest.documents if doc.links)
    resolved = sum(1 for doc in manifest.documents if doc.resolution) + len(finding_resolutions)
    return {
        "document_count": len(manifest.documents),
        "linked_count": linked,
        "resolution_count": resolved,
    }
