"""Data models for scan results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class SourceLocation(BaseModel):
    path: Path
    line: int
    column: int = 0


class VariableRef(BaseModel):
    """A COBOL data item or parameter mentioned near error logic."""

    name: str
    role: str = ""  # e.g. condition, moved-from, compared-with
    line: int | None = None


class ErrorOccurrence(BaseModel):
    """A detected error code / message literal and where it is set."""

    code: str
    literal_kind: str = "numeric"  # numeric | alphanumeric | pattern
    location: SourceLocation
    setting_statement: str = ""
    paragraph: str | None = None
    section: str | None = None
    related: list[VariableRef] = Field(default_factory=list)
    logic_context: str = ""
    condition: str = ""
    parameters_text: str = ""
    error_message_literal: str = ""
    row_summary: str = ""
    #: Logical CORORA / CORORL condition / field (e.g. mapped 88 name), not necessarily the
    #: receiving item in ``setting_statement`` (used when fallback is MOVE to type).
    error_field: str = ""
    #: When a code or field query matched both CORORA and CORORL mapping files, or both
    #: one-char maps contributed, a short human-readable note for the findings table.
    mapping_detail: str = ""


class ProgramSummary(BaseModel):
    """Per-program rollup."""

    program_id: str
    source_path: Path
    occurrences: list[ErrorOccurrence] = Field(default_factory=list)
    plain_english: str = ""
    search_blob: str = ""


class ScanManifest(BaseModel):
    root: Path
    programs: list[ProgramSummary] = Field(default_factory=list)
    generated_at: str = ""

    def to_searchable_records(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for p in self.programs:
            for occ in p.occurrences:
                rows.append(
                    {
                        "program": p.program_id,
                        "file": str(p.source_path),
                        "error_code": occ.code,
                        "error_field": occ.error_field,
                        "line": ("" if occ.location.line == 0 else occ.location.line),
                        "paragraph": occ.paragraph,
                        "section": occ.section,
                        "statement": occ.setting_statement,
                        "condition": occ.condition,
                        "parameters": occ.parameters_text,
                        "error_message": occ.error_message_literal,
                        "row_summary": occ.row_summary,
                        "mapping_detail": occ.mapping_detail,
                        "logic_context": occ.logic_context,
                        "related": [v.model_dump() for v in occ.related],
                        "summary": p.plain_english,
                        "search_text": " ".join(
                            filter(
                                None,
                                [
                                    p.program_id,
                                    occ.code,
                                    occ.error_field,
                                    occ.setting_statement,
                                    occ.condition,
                                    occ.parameters_text,
                                    occ.error_message_literal,
                                    occ.row_summary,
                                    occ.mapping_detail,
                                    occ.paragraph or "",
                                    occ.logic_context[:500] if occ.logic_context else "",
                                    p.plain_english,
                                    p.search_blob,
                                ],
                            )
                        ),
                    }
                )
        return rows
