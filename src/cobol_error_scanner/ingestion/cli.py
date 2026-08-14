"""CLI for operational document ingestion."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

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

console = Console()
app = typer.Typer(
    name="cobol-ingest",
    help="Ingest operational documents and suggest resolutions linked to COBOL scan results.",
    no_args_is_help=True,
)


@app.command()
def ingest(
    docs_root: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        resolve_path=True,
        help="Folder with emails, tickets, PDFs, logs, etc.",
    ),
    scan_out: Path = typer.Option(
        Path("out"),
        "--scan-out",
        help="Directory containing errors.jsonl from cobol-scan",
    ),
    out_dir: Path = typer.Option(Path("out"), "--out", "-o", help="Output directory"),
    rules: Path = typer.Option(
        Path("config/error_rules.json"),
        "--rules",
        "-r",
        exists=True,
        dir_okay=False,
        help="JSON rules used for entity extraction",
    ),
    resolver: str = typer.Option(
        "heuristic",
        "--resolver",
        help="heuristic | openai | ollama (openai needs OPENAI_API_KEY; ollama needs local server)",
    ),
    redact: bool = typer.Option(
        False,
        "--redact",
        help="Redact email addresses and SSN-like patterns in document bodies",
    ),
) -> None:
    """Ingest documents, link to COBOL findings, and write resolution artifacts."""
    scan_out = scan_out.resolve()
    out_dir = out_dir.resolve()
    errors_path = scan_out / "errors.jsonl"
    if not errors_path.is_file():
        console.print(
            f"[red]Missing {errors_path}. Run cobol-scan first to produce errors.jsonl.[/red]"
        )
        raise typer.Exit(1)

    rules_path = resolve_rules_path(rules)
    app_cfg = load_app_config()
    if resolver in LLM_PROVIDERS:
        app_cfg.resolver.provider = resolver

    manifest, finding_resolutions = ingest_root(
        docs_root,
        scan_out=scan_out,
        rules_path=rules_path,
        resolver=resolver,
        redact=redact,
        app_config=app_cfg,
    )

    write_documents_jsonl(manifest, out_dir / "documents.jsonl")
    write_resolutions_jsonl(manifest, out_dir / "resolutions.jsonl", finding_resolutions=finding_resolutions)
    write_documents_table(manifest, out_dir / "documents_table.md")
    if app_cfg.knowledge.merge_on_write:
        errors_rows: list[dict] = []
        with errors_path.open(encoding="utf-8") as f:
            for line in f:
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

    linked = sum(1 for d in manifest.documents if d.links)
    matched = sum(1 for d in manifest.documents if d.metadata.get("term_matched"))
    resolved = sum(1 for d in manifest.documents if d.resolution) + len(finding_resolutions)
    console.print(
        f"Ingested {len(manifest.documents)} document(s); "
        f"{linked} linked to COBOL findings; "
        f"{resolved} resolution(s) written to {out_dir}"
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
