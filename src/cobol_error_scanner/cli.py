"""CLI for COBOL Error Logic Scanner.

Usage (no nested ``run`` subcommand — avoids ``cobol-scan run run`` mistakes)::

    cobol-scan samples --rules config/error_rules.json --out out
    py -m cobol_error_scanner.cli samples -r config/error_rules.json
    py -m cobol_error_scanner.cli samples -e E102
       writes out/error_table.md (only that code). Full scan uses errors_table.md by default.
    py -m cobol_error_scanner.cli samples -f ERR-NO-SEC-EDD-OVRD
       CORORA mapping substring search; writes error_field_table.md by default.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from cobol_error_scanner.mapping_catalog import MAX_ERROR_FIELD_INPUT_LEN, resolve_mapping_directory
from cobol_error_scanner.mapping_resolve import (
    apply_mapping_filter_fallback,
    resolve_mapped_error_field,
)
from cobol_error_scanner.docgen import build_manifest, write_jsonl, write_manifest_json, write_markdown_table
from cobol_error_scanner.pipeline import filter_programs_by_error_code, scan_root
from cobol_error_scanner.summarizer import SummarizerConfig

console = Console()


def scan(
    source_root: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        resolve_path=True,
        help="Root folder with .cbl/.cob/.cpy",
    ),
    rules: Path = typer.Option(
        Path("config/error_rules.json"),
        "--rules",
        "-r",
        exists=True,
        dir_okay=False,
        help="JSON config: return_code_fields + error_patterns",
    ),
    out_dir: Path = typer.Option(Path("out"), "--out", "-o", help="Output directory"),
    summarizer: str = typer.Option(
        "heuristic",
        "--summarizer",
        "-s",
        help="heuristic | openai (needs OPENAI_API_KEY + pip install openai)",
    ),
    error_code: str | None = typer.Option(
        None,
        "--error-code",
        "-e",
        help="Only include findings with this code (case-insensitive). Table defaults to error_table.md.",
    ),
    error_field: str | None = typer.Option(
        None,
        "--error-field",
        "-f",
        help=(
            "88-level name substring (max 30 chars) against CORORA and CORORL mapping copybooks, "
            "e.g. ERR-… matches CORORA-R-ERR-… and CORORL-R-ERR-…. "
            "If set, takes precedence over --error-code and skips the general COBOL rules scan."
        ),
    ),
    corora_mappings: Path | None = typer.Option(
        None,
        "--corora-mappings",
        help=(
            "Folder with CORORA_* / CORORL_* mapping fragments "
            "(CORORA_TWO_CHAR_ERROR, CORORL_TWO_CHAR_ERROR, etc.; default: error_mapping_files)."
        ),
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
    table_name: str | None = typer.Option(
        None,
        "--table",
        "-t",
        help=(
            "Markdown table under --out. Defaults: errors_table.md (full scan), "
            "error_table.md (--error-code), error_field_table.md (--error-field)."
        ),
    ),
) -> None:
    """Scan COBOL sources and emit searchable documentation."""
    cfg = SummarizerConfig(provider=summarizer if summarizer in {"heuristic", "openai"} else "heuristic")

    ef_raw = (error_field or "").strip()
    if len(ef_raw) > MAX_ERROR_FIELD_INPUT_LEN:
        console.print(
            f"[yellow]Note:[/yellow] error field input truncated to {MAX_ERROR_FIELD_INPUT_LEN} characters."
        )
    ef = ef_raw[:MAX_ERROR_FIELD_INPUT_LEN]

    ec = (error_code or "").strip() if not ef else ""

    if ef:
        if error_code and (error_code or "").strip():
            console.print("[yellow]Note:[/yellow] --error-field takes precedence; ignoring --error-code.")
        programs = resolve_mapped_error_field(
            source_root,
            ef,
            mapping_dir_explicit=corora_mappings,
            summarizer=cfg,
        )
        resolved_table = (
            table_name.strip()
            if (table_name is not None and table_name.strip() != "")
            else "error_field_table.md"
        )
        table_path = out_dir / Path(resolved_table).name
        if not programs:
            console.print(
                f"[yellow]No findings[/yellow] for error field [bold]{ef!r}[/bold]; "
                f"writing empty table to {table_path.resolve()}"
            )
    else:
        resolved_table = (
            table_name.strip()
            if (table_name is not None and table_name.strip() != "")
            else ("error_table.md" if ec else "errors_table.md")
        )
        table_path = out_dir / Path(resolved_table).name
        programs = scan_root(source_root, rules, summarizer=cfg)
        if ec:
            eu = ec.upper()
            programs_std = filter_programs_by_error_code(programs, ec, summarizer=cfg)
            map_dir = resolve_mapping_directory(source_root, corora_mappings)
            if len(ec) == 2 and eu.startswith("E") and map_dir is not None:
                cor = apply_mapping_filter_fallback(
                    source_root,
                    ec,
                    mapping_dir=corora_mappings,
                    summarizer=cfg,
                )
                programs = cor if cor else programs_std
            else:
                programs = programs_std
                if not programs and len(ec) == 2 and map_dir is not None:
                    programs = apply_mapping_filter_fallback(
                        source_root,
                        ec,
                        mapping_dir=corora_mappings,
                        summarizer=cfg,
                    )
            if not programs:
                console.print(
                    f"[yellow]No findings[/yellow] for error code [bold]{ec}[/bold]; "
                    f"writing empty table to {table_path.resolve()}"
                )

    manifest = build_manifest(source_root, programs)
    write_jsonl(manifest, out_dir / "errors.jsonl")
    write_manifest_json(manifest, out_dir / "manifest.json")
    write_markdown_table(manifest, table_path)
    n = sum(len(p.occurrences) for p in programs)
    if ef:
        filter_note = f" (error field: {ef!r})"
    elif ec:
        filter_note = f" (filtered: {ec})"
    else:
        filter_note = ""
    console.print(
        f"[green]OK[/green] {len(programs)} program(s), {n} finding(s){filter_note} -> {out_dir.resolve()} "
        f"(incl. {table_path.name})"
    )


def main() -> None:
    """Console script entry: ``cobol-scan <SOURCE_ROOT> ...``."""
    typer.run(scan)


if __name__ == "__main__":
    main()
