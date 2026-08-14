#!/usr/bin/env python3
"""Test operational document ingestion for error code D6.

Runs COBOL scan for D6, ingests samples/docs, verifies D6 sample docs link to
D6 findings, and exercises document_access for operational-docs API shape.

Usage:
    py scripts/test_operational_docs_d6.py
    py scripts/test_operational_docs_d6.py --skip-scan
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
RESOLUTIONS = OUT / "resolutions.jsonl"

EXPECTED_DOCS = (
    "incident-D6-no-agreement.txt",
    "incident-D6-line1-comment.txt",
    "slack-chat-D6.json",
    "support-email-D6.eml",
)

SE_ONLY_DOCS = (
    "incident-SE-terms-override.txt",
    "slack-chat-SE.json",
    "support-email-SE.eml",
    "runbook-SE-terms-override.docx",
)

D6_CORORA_FIELD = "CORORA-R-ERROR-NO-AGREEMENT"
D6_CORORL_FIELD = "CORORL-R-ERROR-LINE1-NOT-CMNT"


def run_scan() -> None:
    cmd = [
        sys.executable,
        "-m",
        "cobol_error_scanner.cli",
        str(SAMPLES),
        "-e",
        "D6",
        "-o",
        str(OUT),
    ]
    print("Scan:", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def run_ingest() -> None:
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


def _split_csv(value: str) -> set[str]:
    return {part.strip().upper() for part in value.split(",") if part.strip()}


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


def test_operational_docs_api(findings: list[dict]) -> list[str]:
    """Call document_access for each D6 finding row index."""
    sys.path.insert(0, str(ROOT / "src"))
    from cobol_error_scanner.document_access import get_operational_docs_for_finding

    failures: list[str] = []
    d6_rows = [
        (i, r)
        for i, r in enumerate(findings)
        if str(r.get("error_code", "")).upper() == "D6"
    ]
    if not d6_rows:
        failures.append("No D6 rows in findings list for API test")
        return failures

    for idx, row in d6_rows:
        result = get_operational_docs_for_finding(row, OUT)
        prog = row.get("program", "")
        field = row.get("error_field", "")
        n_docs = result.get("document_count", 0)
        summary = str(result.get("summary", ""))[:80]
        print(
            f"  API finding[{idx}] {prog} {field}: "
            f"{n_docs} doc(s), summary={summary!r}..."
        )
        if not result.get("has_artifacts"):
            failures.append(f"finding[{idx}]: has_artifacts false")
        elif n_docs == 0:
            failures.append(f"finding[{idx}] {prog}: no linked operational documents")
        elif not result.get("summary") and not result.get("steps"):
            failures.append(f"finding[{idx}] {prog}: no resolution summary or steps")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-scan",
        action="store_true",
        help="Use existing out/errors.jsonl (must contain D6 findings)",
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
    d6_findings = [r for r in findings if str(r.get("error_code", "")).upper() == "D6"]
    if not d6_findings:
        print("No D6 findings in errors.jsonl. Run scan first:")
        print(f"  py -m cobol_error_scanner.cli {SAMPLES} -e D6 -o {OUT}")
        return 1
    print(f"D6 findings in scan: {len(d6_findings)}")
    for r in d6_findings:
        print(
            f"  - {r.get('program')} | {r.get('error_field')} | line {r.get('line')}"
        )

    run_ingest()

    docs = load_jsonl(DOCUMENTS)
    if not docs:
        print("No rows in", DOCUMENTS)
        return 1

    failures: list[str] = []
    for name in SE_ONLY_DOCS:
        row = next(
            (d for d in docs if name in str(d.get("source_path", ""))),
            None,
        )
        if row is None:
            continue
        codes = _split_csv(str(row.get("linked_error_codes") or ""))
        if "D6" in codes:
            failures.append(f"{name}: SE document must not link to D6 (got codes {codes})")

    for name in EXPECTED_DOCS:
        row = next(
            (d for d in docs if name in str(d.get("source_path", ""))),
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
        fields = {str(l.get("error_field", "")).upper() for l in links}
        if "D6" not in codes:
            failures.append(f"{name}: links present but not to D6 ({codes})")
            continue
        d6_fields_ok = (
            D6_CORORA_FIELD.upper() in fields
            or D6_CORORL_FIELD.upper() in fields
            or any("D6" in str(l.get("evidence", "")).upper() for l in links)
        )
        if not d6_fields_ok and name.startswith("incident-D6-line1"):
            if D6_CORORL_FIELD.upper() not in fields:
                failures.append(f"{name}: expected {D6_CORORL_FIELD} link")
                continue
        if not d6_fields_ok and "no-agreement" in name:
            if D6_CORORA_FIELD.upper() not in fields:
                failures.append(f"{name}: expected {D6_CORORA_FIELD} link")
                continue
        res = row.get("resolution_summary", "")
        print(
            f"OK  {name} -> {len(links)} link(s), type={row.get('doc_type')}, "
            f"resolution={res[:60]}..."
        )

    print(f"\nIngested {len(docs)} document(s) total")
    res_rows = load_jsonl(RESOLUTIONS)
    d6_res = [r for r in res_rows if "D6" in str(r.get("linked_error_codes", ""))]
    print(f"Resolution rows mentioning D6: {len(d6_res)}")

    print("\nOperational-docs API (document_access):")
    api_failures = test_operational_docs_api(findings)
    failures.extend(api_failures)

    sys.path.insert(0, str(ROOT / "src"))
    from cobol_error_scanner.document_access import get_operational_docs_for_finding

    for idx, row in enumerate(findings):
        if str(row.get("error_code", "")).upper() != "D6":
            continue
        result = get_operational_docs_for_finding(row, OUT)
        for doc in result.get("documents", []):
            path = str(doc.get("source_path", ""))
            if any(name in path for name in SE_ONLY_DOCS):
                failures.append(f"API: SE sample {path} returned for D6 finding index {idx}")

    if failures:
        print("\nFailures:")
        for msg in failures:
            print(" ", msg)
        return 1
    print("\nAll D6 operational document tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
