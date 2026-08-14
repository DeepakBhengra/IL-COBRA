"""Load and filter COBOL scan findings from JSONL/manifest artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from cobol_error_scanner.mapping_catalog import MAX_ERROR_FIELD_INPUT_LEN, validate_error_field_query

TABLE_COLUMNS = [
    "error_code",
    "error_field",
    "program",
    "line",
    "paragraph",
    "section",
    "condition",
    "parameters",
    "error_message",
    "row_summary",
    "mapping_detail",
]

DETAIL_FIELDS = [
    ("Program", "program"),
    ("Error code", "error_code"),
    ("Error Field", "error_field"),
    ("File", "file"),
    ("Line", "line"),
    ("Paragraph", "paragraph"),
    ("Section", "section"),
    ("Condition", "condition"),
    ("Parameters", "parameters"),
    ("Error message", "error_message"),
    ("Statement", "statement"),
    ("Summary", "row_summary"),
    ("Mapping detail", "mapping_detail"),
]

_MOVE_TO_TARGET = re.compile(r"\bMOVE\s+.+?\s+TO\s+([\w-]+)", re.IGNORECASE)
_SET_TO_TARGET = re.compile(r"\bSET\s+([\w-]+)\s+TO\s+\S+", re.IGNORECASE)

TabFilter = Literal["all", "two_char", "patterns", "mapped"]


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def extract_error_field(statement: str) -> str:
    """Return the COBOL field or condition name that receives the error mapping."""
    text = statement.strip()
    if not text:
        return ""
    for pattern in (_MOVE_TO_TARGET, _SET_TO_TARGET):
        match = pattern.search(text)
        if match:
            return match.group(1)
    return ""


def load_records(jsonl_path: str | Path) -> list[dict[str, Any]]:
    path = Path(jsonl_path)
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_manifest(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def records_to_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    for column in set(
        TABLE_COLUMNS + ["file", "statement", "logic_context", "related", "summary", "search_text", "mapping_detail"]
    ):
        if column not in frame.columns:
            frame[column] = ""
    frame["error_field"] = frame.apply(
        lambda row: row["error_field"] or extract_error_field(str(row.get("statement", ""))),
        axis=1,
    )
    if "line" in frame.columns:

        def _normalize_line_cell(v: Any) -> Any:
            if v == "" or v is None:
                return ""
            if isinstance(v, float) and pd.isna(v):
                return ""
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return v

        frame["line"] = frame["line"].map(_normalize_line_cell)
    return frame


def apply_tab_filter(frame: pd.DataFrame, tab: TabFilter) -> pd.DataFrame:
    if tab == "all" or frame.empty:
        return frame
    filtered = frame.copy()
    codes = filtered["error_code"].fillna("").astype(str)
    if tab == "two_char":
        return filtered[codes.str.len() == 2]
    if tab == "patterns":
        return filtered[codes.str.len() != 2]
    if tab == "mapped":
        field = filtered["error_field"].fillna("").astype(str).str.strip()
        detail = filtered["mapping_detail"].fillna("").astype(str).str.strip()
        return filtered[(field != "") | (detail != "")]
    return filtered


def filter_frame(
    frame: pd.DataFrame,
    *,
    programs: list[str] | None = None,
    error_codes: list[str] | None = None,
    query: str = "",
    field_contains: str = "",
    tab: TabFilter = "all",
) -> pd.DataFrame:
    """Apply all filters without Streamlit UI dependencies."""
    filtered = frame.copy()

    if programs:
        filtered = filtered[filtered["program"].isin(programs)]

    if error_codes:
        typed_codes = [code.upper() for code in error_codes]
        filtered = filtered[filtered["error_code"].astype(str).str.upper().isin(typed_codes)]

    if query.strip():
        haystack = (
            filtered["search_text"].fillna("").astype(str)
            + " "
            + filtered["error_field"].fillna("").astype(str)
        ).str.lower()
        filtered = filtered[haystack.str.contains(query.strip().lower(), regex=False)]

    fc = field_contains.strip()[:MAX_ERROR_FIELD_INPUT_LEN]
    if fc:
        validate_error_field_query(fc)
        col = filtered["error_field"].fillna("").astype(str).str.lower()
        filtered = filtered[col.str.contains(fc.lower(), regex=False)]

    return apply_tab_filter(filtered, tab)


def parse_error_code_tokens(error_code_input: str) -> tuple[list[str], list[str]]:
    """Return (valid 2-char tokens uppercased, invalid tokens)."""
    raw_tokens = [token.strip() for token in error_code_input.replace(",", " ").split() if token.strip()]
    invalid = [token for token in raw_tokens if len(token) != 2]
    valid = [token.upper() for token in raw_tokens if len(token) == 2]
    return valid, invalid


def compute_metrics(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty:
        return {"findings": 0, "programs": 0, "error_codes": 0, "source_files": 0}
    return {
        "findings": len(frame),
        "programs": int(frame["program"].nunique()),
        "error_codes": int(frame["error_code"].nunique()),
        "source_files": int(frame["file"].nunique()),
    }


def compute_tab_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {
        "all": len(frame),
        "two_char": len(apply_tab_filter(frame, "two_char")),
        "patterns": len(apply_tab_filter(frame, "patterns")),
        "mapped": len(apply_tab_filter(frame, "mapped")),
    }


def paginate_frame(
    frame: pd.DataFrame,
    *,
    page: int = 1,
    page_size: int = 100,
    sort: str | None = None,
    sort_dir: Literal["asc", "desc"] = "asc",
) -> tuple[pd.DataFrame, int, int]:
    """Return (page slice, total rows, total pages)."""
    if frame.empty:
        return frame, 0, 0

    working = frame.copy()
    if sort and sort in working.columns:
        working = working.sort_values(sort, ascending=(sort_dir == "asc"), kind="mergesort")

    total = len(working)
    page_size = max(1, min(page_size, 500))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    return working.iloc[start:end], total, total_pages


def program_summary_for(manifest: dict[str, Any], program_id: str) -> str:
    for program in manifest.get("programs", []):
        if isinstance(program, dict) and program.get("program_id") == program_id:
            return str(program.get("plain_english", ""))
    return ""
