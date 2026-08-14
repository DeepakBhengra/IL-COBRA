"""Run COBOL scans and write output artifacts."""

from __future__ import annotations

import os
from pathlib import Path

from cobol_error_scanner.docgen import build_manifest, write_jsonl, write_manifest_json, write_markdown_table
from cobol_error_scanner.mapping_catalog import MAX_ERROR_FIELD_INPUT_LEN, resolve_mapping_directory
from cobol_error_scanner.mapping_resolve import apply_mapping_filter_fallback, resolve_mapped_error_field
from cobol_error_scanner.paths import (
    DEFAULT_CORORA_MAPPINGS,
    DEFAULT_OUT_DIR,
    DEFAULT_RULES_PATH,
    DEFAULT_SOURCE_ROOT,
    REPO_ROOT,
)
from cobol_error_scanner.pipeline import filter_programs_by_error_code, scan_root
from cobol_error_scanner.llm_client import LLM_PROVIDERS
from cobol_error_scanner.summarizer import SummarizerConfig


def optional_path(raw: str) -> Path | None:
    raw = raw.strip()
    return Path(raw) if raw else None


def _summarizer_config(provider: str) -> SummarizerConfig:
    if provider not in LLM_PROVIDERS:
        provider = "heuristic"
    return SummarizerConfig(provider=provider)


def run_scan(
    source_root: Path,
    rules_path: Path,
    out_dir: Path,
    summarizer: str,
    *,
    error_code: str = "",
    error_field: str = "",
    corora_mappings: Path | None = None,
) -> tuple[int, int, str]:
    ef = error_field.strip()[:MAX_ERROR_FIELD_INPUT_LEN]
    if ef:
        config = _summarizer_config(summarizer)
        programs = resolve_mapped_error_field(
            source_root,
            ef,
            mapping_dir_explicit=corora_mappings,
            summarizer=config,
        )
        table_name = "error_field_table.md"
        manifest = build_manifest(source_root, programs)
        write_jsonl(manifest, out_dir / "errors.jsonl")
        write_manifest_json(manifest, out_dir / "manifest.json")
        write_markdown_table(manifest, out_dir / table_name)
        finding_count = sum(len(program.occurrences) for program in programs)
        return len(programs), finding_count, table_name

    requested_code = error_code.strip().upper()
    if requested_code and len(requested_code) != 2:
        raise ValueError(f"Focused error-code scans require exactly 2 characters: {requested_code!r}")

    config = _summarizer_config(summarizer)
    programs = scan_root(source_root, rules_path, summarizer=config)
    table_name = "errors_table.md"

    if requested_code:
        standard_matches = filter_programs_by_error_code(programs, requested_code, summarizer=config)
        mapping_dir = resolve_mapping_directory(source_root, corora_mappings)
        corora_matches = []
        if mapping_dir is not None:
            corora_matches = apply_mapping_filter_fallback(
                source_root,
                requested_code,
                mapping_dir=corora_mappings,
                summarizer=config,
            )
        programs = corora_matches if corora_matches else standard_matches
        table_name = "error_table.md"

    manifest = build_manifest(source_root, programs)
    write_jsonl(manifest, out_dir / "errors.jsonl")
    write_manifest_json(manifest, out_dir / "manifest.json")
    write_markdown_table(manifest, out_dir / table_name)
    finding_count = sum(len(program.occurrences) for program in programs)
    return len(programs), finding_count, table_name


def default_config() -> dict[str, str]:
    docs_root = os.environ.get("COBOL_DOCS_ROOT", "").strip()
    if not docs_root:
        sample_docs = REPO_ROOT / "samples" / "docs"
        if sample_docs.is_dir():
            docs_root = str(sample_docs)
    return {
        "source_root": str(DEFAULT_SOURCE_ROOT),
        "rules_path": str(DEFAULT_RULES_PATH),
        "out_dir": str(DEFAULT_OUT_DIR),
        "corora_mappings": str(DEFAULT_CORORA_MAPPINGS),
        "docs_root": docs_root,
    }
