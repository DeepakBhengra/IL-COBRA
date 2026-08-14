"""CSV export helpers for findings tables."""

from __future__ import annotations

import pandas as pd

from cobol_error_scanner.data_access import TABLE_COLUMNS, format_value


def build_csv_bytes(frame: pd.DataFrame, *, indices: list[int] | None = None) -> bytes:
    """Build CSV bytes from a findings DataFrame, optionally subset by row indices."""
    if indices is not None:
        subset = frame.iloc[indices].copy()
    else:
        subset = frame.copy()

    csv_table = subset[TABLE_COLUMNS + ["file", "statement", "logic_context"]].copy()
    for column in csv_table.columns:
        if csv_table[column].dtype == object:
            csv_table[column] = csv_table[column].map(format_value)
    csv_table = csv_table.rename(columns={"error_field": "Error Field"})
    csv_table.insert(0, "S.No", range(1, len(csv_table) + 1))
    return csv_table.to_csv(index=False).encode("utf-8")


def build_display_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Table for HTML display with S.No column."""
    table = frame[TABLE_COLUMNS].copy()
    for column in table.columns:
        if table[column].dtype == object:
            table[column] = table[column].map(format_value)
    table = table.rename(columns={"error_field": "Error Field"})
    table.insert(0, "S.No", range(1, len(table) + 1))
    return table
