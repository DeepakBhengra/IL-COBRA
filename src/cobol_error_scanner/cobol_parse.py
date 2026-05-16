"""Lightweight COBOL structure + statement extraction (subset; not a full compiler front-end)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Paragraph:
    name: str
    start_line: int
    end_line: int
    lines: list[str] = field(default_factory=list)


@dataclass
class Section:
    name: str
    start_line: int
    paragraphs: list[Paragraph] = field(default_factory=list)


def _strip_comment(line: str) -> str:
    """Remove COBOL fixed-format sequence area and trailing comments (best-effort)."""
    if len(line) > 6:
        body = line[6:72] if len(line) >= 72 else line[6:]
    else:
        body = line
    if "*>" in body:
        body = body.split("*>", 1)[0]
    return body.rstrip()


class CobolStructureParser:
    """Extract sections/paragraphs and normalized source lines in PROCEDURE DIVISION."""

    # Lines like ``END-EVALUATE.`` match ``NAME.`` but are block terminators, not paragraphs.
    _NOT_PARAGRAPH_NAMES = frozenset(
        {
            "ELSE",
            "EXIT",
            "WHEN",
            "END-IF",
            "END-PERFORM",
            "END-EVALUATE",
            "END-SEARCH",
            "END-STRING",
            "END-UNSTRING",
            "END-READ",
            "END-WRITE",
            "END-START",
            "END-RETURN",
            "END-DELETE",
            "END-RECEIVE",
            "END-ACCEPT",
            "END-DISPLAY",
            "END-XML",
            "END-JSON",
            "END-INVOKE",
            "END-EXEC",
        }
    )

    _para = re.compile(r"^(\s*)([\w-]+)\s*\.\s*$", re.IGNORECASE)
    _section = re.compile(r"^(\s*)([\w-]+)\s+SECTION\s*\.\s*$", re.IGNORECASE)

    def parse_lines(self, lines: list[str]) -> tuple[list[str], list[Section]]:
        norm: list[str] = []
        for raw in lines:
            norm.append(_strip_comment(raw.rstrip("\n")))

        sections: list[Section] = []
        current_section: Section | None = None
        para_stack: list[tuple[str, int]] = []

        def close_paragraph(end_line: int) -> None:
            nonlocal para_stack, current_section
            if not para_stack or current_section is None:
                return
            name, start = para_stack.pop()
            block = norm[start - 1 : end_line]
            current_section.paragraphs.append(
                Paragraph(name=name, start_line=start, end_line=end_line, lines=block)
            )

        in_procedure = False
        for i, line in enumerate(norm, start=1):
            u = line.upper()
            if "PROCEDURE DIVISION" in u:
                in_procedure = True
                current_section = Section(name="DEFAULT", start_line=i, paragraphs=[])
                sections.append(current_section)
                continue
            if not in_procedure:
                continue

            m_sec = self._section.match(line)
            if m_sec:
                while para_stack:
                    close_paragraph(i - 1)
                name = m_sec.group(2).upper()
                if sections and sections[-1].name == "DEFAULT" and not sections[-1].paragraphs:
                    sections.pop()
                current_section = Section(name=name, start_line=i, paragraphs=[])
                sections.append(current_section)
                continue

            m_p = self._para.match(line)
            if m_p and current_section is not None:
                name = m_p.group(2).upper()
                if name in self._NOT_PARAGRAPH_NAMES:
                    continue
                # Continued clauses (``MOVE … TO`` / ``TO`` targets) sit in Area B; real
                # paragraph headers in fixed format usually start in Area A (<=4 spaces).
                if len(m_p.group(1)) > 4:
                    continue
                while para_stack:
                    close_paragraph(i - 1)
                para_stack.append((name, i))

        last = len(norm)
        while para_stack and current_section is not None:
            close_paragraph(last)

        return norm, sections


def paragraph_for_line(sections: list[Section], line_no: int) -> tuple[str | None, str | None]:
    for sec in sections:
        for para in sec.paragraphs:
            if para.start_line <= line_no <= para.end_line:
                return sec.name, para.name
    return None, None


def paragraph_start_line_for_source_line(sections: list[Section], line_no: int) -> int | None:
    """1-based first line of the paragraph containing ``line_no``, or None if unknown."""
    for sec in sections:
        for para in sec.paragraphs:
            if para.start_line <= line_no <= para.end_line:
                return para.start_line
    return None
