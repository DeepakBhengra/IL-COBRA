#!/usr/bin/env python3
"""Quick verify D1 scan + operational docs linkage."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
sys.path.insert(0, str(ROOT / "src"))

from cobol_error_scanner.document_access import get_operational_docs_for_finding  # noqa: E402


def main() -> int:
    findings = [
        json.loads(line)
        for line in (OUT / "errors.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    d1_rows = [(i, r) for i, r in enumerate(findings) if str(r.get("error_code", "")).upper() == "D1"]
    print(f"D1 findings in scan: {len(d1_rows)}")

    docs = [
        json.loads(line)
        for line in (OUT / "documents.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    d1_docs = [
        d
        for d in docs
        if "D1" in str(d.get("linked_error_codes", "")).upper()
        or any(str(l.get("error_code", "")).upper() == "D1" for l in (d.get("links") or []))
    ]
    print(f"Documents linked to D1: {len(d1_docs)}")
    for d in d1_docs:
        print(f"  - {Path(d.get('source_path', '')).name}")

    if not d1_rows:
        return 1
    idx, row = d1_rows[0]
    result = get_operational_docs_for_finding(row, OUT)
    print(
        f"API finding[{idx}] {row.get('program')} line {row.get('line')}: "
        f"document_count={result.get('document_count')}, "
        f"summary={str(result.get('summary', ''))[:100]!r}"
    )
    for d in result.get("documents", []):
        print(f"  linked: {d.get('title')} ({d.get('doc_type')})")

    ok = len(d1_rows) >= 1 and len(d1_docs) >= 1 and result.get("document_count", 0) >= 1
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
