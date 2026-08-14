#!/usr/bin/env python3
"""Test operational document ingestion for CORORA error code SE.

Runs COBOL scan for SE, ingests samples/docs, and verifies each sample doc
links to at least one SE finding.

Usage:
    python scripts/test_operational_docs_se.py
    python scripts/test_operational_docs_se.py --skip-scan
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
DOCS = SAMPLES / "docs"
OUT = ROOT / "out"
ERRORS = OUT / "errors.jsonl"
DOCUMENTS = OUT / "documents.jsonl"

EXPECTED_DOCS = (
    "incident-SE-terms-override.txt",
    "slack-chat-SE.json",
    "support-email-SE.eml",
    "runbook-SE-terms-override.docx",
)

SE_FIELD = "CORORA-R-ERR-NO-SEC-TERM-OVRD"

D6_ONLY_DOCS = (
    "incident-D6-no-agreement.txt",
    "incident-D6-line1-comment.txt",
    "slack-chat-D6.json",
    "support-email-D6.eml",
)


def run_scan() -> None:
    cmd = [
        sys.executable,
        "-m",
        "cobol_error_scanner.cli",
        str(SAMPLES),
        "-e",
        "SE",
        "-o",
        str(OUT),
    ]
    print("Scan:", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def run_ingest() -> None:
    # cobol-ingest / ingestion.cli: docs folder is the first positional arg (no subcommand).
    cmd = [
        sys.executable,
        "-m",
        "cobol_error_scanner.ingestion.cli",
        str(DOCS),
        "--scan-out",
        str(OUT),
        "--out",
        str(OUT),
        "--resolver",
        "heuristic",
    ]
    print("Ingest:", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-scan",
        action="store_true",
        help="Use existing out/errors.jsonl (must contain SE findings)",
    )
    args = parser.parse_args()

    missing = [name for name in EXPECTED_DOCS if not (DOCS / name).is_file()]
    if missing:
        print("Missing sample documents in samples/docs/:", ", ".join(missing))
        return 1

    if not args.skip_scan:
        run_scan()
    else:
        print("Skipping scan; using", ERRORS)

    findings = load_jsonl(ERRORS)
    se_findings = [
        r
        for r in findings
        if str(r.get("error_code", "")).upper() == "SE"
        or SE_FIELD.upper() in str(r.get("error_field", "")).upper()
    ]
    if not se_findings:
        print("No SE findings in errors.jsonl. Run scan first:")
        print(f"  py -m cobol_error_scanner.cli {SAMPLES} -e SE -o {OUT}")
        return 1
    print(f"SE findings in scan: {len(se_findings)}")

    run_ingest()

    docs = load_jsonl(DOCUMENTS)
    if not docs:
        print("No rows in", DOCUMENTS)
        return 1

    failures: list[str] = []
    for name in EXPECTED_DOCS:
        row = next(
            (d for d in docs if name in str(d.get("source_path", d.get("path", "")))),
            None,
        )
        if row is None:
            failures.append(f"{name}: not ingested")
            continue
        links = row.get("links") or []
        if not links:
            failures.append(f"{name}: ingested but no links to COBOL findings")
            continue
        codes = {str(l.get("error_code", "")).upper() for l in links}
        if "SE" not in codes and not any(SE_FIELD in str(l.get("error_field", "")) for l in links):
            failures.append(f"{name}: links present but not to SE ({codes})")
            continue
        print(f"OK  {name} -> {len(links)} link(s), types={row.get('doc_type')}")

    print(f"\nIngested {len(docs)} document(s); SE-linked samples: {len(EXPECTED_DOCS) - len(failures)}/{len(EXPECTED_DOCS)}")

    print("\nOperational-docs API (document_access):")
    sys.path.insert(0, str(ROOT / "src"))
    from cobol_error_scanner.document_access import get_operational_docs_for_finding

    for idx, row in enumerate(se_findings):
        result = get_operational_docs_for_finding(row, OUT)
        n_docs = result.get("document_count", 0)
        prog = row.get("program", "")
        print(f"  API finding[{idx}] {prog} SE: {n_docs} doc(s)")
        if not result.get("has_artifacts"):
            failures.append(f"finding[{idx}]: has_artifacts false")
        elif n_docs == 0:
            failures.append(f"finding[{idx}] {prog}: no operational documents for SE")
        for doc in result.get("documents", []):
            path = str(doc.get("source_path", ""))
            if any(name in path for name in D6_ONLY_DOCS):
                failures.append(f"API: D6 sample {path} returned for SE finding index {idx}")

    if failures:
        print("\nFailures:")
        for msg in failures:
            print(" ", msg)
        return 1
    print("\nAll SE operational document samples linked successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
