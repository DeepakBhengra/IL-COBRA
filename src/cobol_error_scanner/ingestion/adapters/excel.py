"""Excel (.xlsx, .xls) adapter."""

from __future__ import annotations

from pathlib import Path

from cobol_error_scanner.ingestion.adapters.base import _base_document
from cobol_error_scanner.ingestion.models import DocumentType, OperationalDocument

_MAX_ROWS_PER_SHEET = 500


class ExcelAdapter:
    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in {".xlsx", ".xls"}

    def extract(self, path: Path) -> OperationalDocument:
        warnings: list[str] = []
        parts: list[str] = []
        sheet_names: list[str] = []
        try:
            import pandas as pd

            sheets = pd.read_excel(path, sheet_name=None, header=0, dtype=str)
            if not isinstance(sheets, dict):
                sheets = {"Sheet1": sheets}
            for sheet_name, frame in sheets.items():
                sheet_names.append(str(sheet_name))
                if frame is None or frame.empty:
                    continue
                truncated = frame.head(_MAX_ROWS_PER_SHEET)
                if len(frame) > _MAX_ROWS_PER_SHEET:
                    warnings.append(f"{sheet_name}: truncated at {_MAX_ROWS_PER_SHEET} rows")
                text = truncated.fillna("").to_csv(index=False, lineterminator="\n")
                if text.strip():
                    parts.append(f"## Sheet: {sheet_name}\n{text}")
        except ImportError:
            warnings.append("pandas/openpyxl not available for Excel read")
        except Exception as exc:
            warnings.append(str(exc))

        body = "\n\n".join(parts)
        return _base_document(
            path,
            doc_type=DocumentType.excel,
            title=path.stem,
            body=body,
            metadata={"sheets": sheet_names, "warnings": warnings},
        )
