"""Generic CSV adapter (non-ticket, non-chat exports)."""

from __future__ import annotations

import csv
from pathlib import Path

from cobol_error_scanner.ingestion.adapters.base import _base_document
from cobol_error_scanner.ingestion.adapters.chat import ChatAdapter
from cobol_error_scanner.ingestion.adapters.ticket import TicketAdapter
from cobol_error_scanner.ingestion.models import DocumentType, OperationalDocument

_MAX_ROWS = 500


def _is_ticket_or_chat_csv(path: Path) -> bool:
    return TicketAdapter().supports(path) or ChatAdapter().supports(path)


class CsvGenericAdapter:
    def supports(self, path: Path) -> bool:
        if path.suffix.lower() != ".csv":
            return False
        return not _is_ticket_or_chat_csv(path)

    def extract(self, path: Path) -> OperationalDocument:
        warnings: list[str] = []
        rows: list[dict[str, str]] = []
        try:
            with path.open(encoding="utf-8", errors="replace", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    for i, row in enumerate(reader):
                        if i >= _MAX_ROWS:
                            warnings.append(f"truncated at {_MAX_ROWS} rows")
                            break
                        rows.append({k: (v or "") for k, v in row.items()})
        except Exception as exc:
            warnings.append(str(exc))

        parts: list[str] = []
        for row in rows[:50]:
            line = " | ".join(f"{k}={v}" for k, v in row.items() if v and str(v).strip())
            if line.strip():
                parts.append(line)
        body = "\n".join(parts)
        if not body and rows:
            body = "\n".join(str(r) for r in rows[:20])

        return _base_document(
            path,
            doc_type=DocumentType.csv,
            title=path.stem,
            body=body,
            metadata={"row_count": len(rows), "warnings": warnings},
        )
