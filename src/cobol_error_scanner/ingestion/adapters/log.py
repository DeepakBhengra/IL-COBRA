"""Production log adapter (.log, .jsonl, log-like .txt)."""

from __future__ import annotations

import json
from pathlib import Path

from cobol_error_scanner.ingestion.adapters.base import _base_document
from cobol_error_scanner.ingestion.models import DocumentType, OperationalDocument


def _is_log_file(path: Path) -> bool:
    suf = path.suffix.lower()
    if suf in {".log", ".jsonl"}:
        return True
    if suf == ".txt":
        name = path.stem.lower()
        return any(tok in name for tok in ("log", "trace", "stderr", "production"))
    return False


class LogAdapter:
    def supports(self, path: Path) -> bool:
        return _is_log_file(path)

    def extract(self, path: Path) -> OperationalDocument:
        if path.suffix.lower() == ".jsonl":
            lines: list[str] = []
            for i, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
                if i >= 5000:
                    break
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                    msg = obj.get("message") or obj.get("msg") or obj.get("text") or raw
                    level = obj.get("level") or obj.get("severity") or ""
                    lines.append(f"[{level}] {msg}".strip())
                except json.JSONDecodeError:
                    lines.append(raw)
            body = "\n".join(lines)
        else:
            body = path.read_text(encoding="utf-8", errors="replace")
        return _base_document(
            path,
            doc_type=DocumentType.log,
            title=path.stem,
            body=body,
            metadata={"format": path.suffix.lower()},
        )
