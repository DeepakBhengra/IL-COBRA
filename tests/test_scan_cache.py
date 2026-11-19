"""Saved scan results are reused until a COBOL source file changes."""

from __future__ import annotations

import os
from pathlib import Path

from cobol_error_scanner.scan_service import run_scan

RULES = Path(__file__).resolve().parents[1] / "config" / "error_rules.json"


def _program(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def test_second_scan_loads_saved_results_until_cobol_changes(tmp_path: Path):
    source = tmp_path / "cobol"
    source.mkdir()
    program = _program(
        source,
        "PROG.cob",
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PROG.\n",
    )
    out = tmp_path / "out"

    first = run_scan(source, RULES, out, "heuristic", error_code="EV")
    assert first.from_saved is False
    saved_errors = (out / "saved_scans").rglob("errors.jsonl")
    assert any(saved_errors)

    second = run_scan(source, RULES, out, "heuristic", error_code="EV")
    assert second.from_saved is True
    assert second.program_count == first.program_count
    assert second.finding_count == first.finding_count
    assert second.table_name == first.table_name
    assert (out / "errors.jsonl").is_file()

    other = run_scan(source, RULES, out, "heuristic", error_code="SE")
    assert other.from_saved is False

    program.write_text(program.read_text(encoding="utf-8") + "      * edited\n", encoding="utf-8")
    os.utime(program, (program.stat().st_atime, program.stat().st_mtime + 5))
    third = run_scan(source, RULES, out, "heuristic", error_code="EV")
    assert third.from_saved is False
