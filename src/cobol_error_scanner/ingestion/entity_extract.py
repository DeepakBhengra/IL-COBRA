"""Rule-based entity extraction from operational document text."""

from __future__ import annotations

import json
import re
from pathlib import Path

from cobol_error_scanner.ingestion.document_search import _mentions_code
from cobol_error_scanner.ingestion.models import ExtractedEntity
from cobol_error_scanner.mapping_catalog import MAPPING_FAMILIES, MAX_ERROR_FIELD_INPUT_LEN

_PROGRAM_RE = re.compile(r"\b([A-Z]{2,3}\d{3,6})\b")
_QUOTED_CODE_RE = re.compile(r"['\"]([A-Z0-9]{2,8})['\"]")
_TWO_CHAR_CODE_RE = re.compile(r"\berror\s*(?:code)?\s*[:=]?\s*([A-Z0-9]{2})\b", re.IGNORECASE)
_CORORA_RE = re.compile(
    r"\b("
    + "|".join(rf"{fam}-R-[A-Z0-9-]{{1,30}}" for fam in MAPPING_FAMILIES)
    + r"|ERR-[A-Z0-9-]{1,30})\b",
    re.IGNORECASE,
)
_TWO_CHAR_BOUNDARY = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{2})(?![A-Z0-9])", re.IGNORECASE)

_SYMPTOM_HINTS = (
    "timeout",
    "failed",
    "failure",
    "abend",
    "sqlcode",
    "invalid",
    "missing",
    "not found",
    "error",
    "exception",
)


def load_error_code_patterns(rules_path: Path | None = None) -> list[str]:
    if rules_path is None:
        from cobol_error_scanner.project_paths import default_rules_path

        rules_path = default_rules_path()
    if not rules_path.is_file():
        return []
    data = json.loads(rules_path.read_text(encoding="utf-8"))
    patterns: list[str] = []
    for field in ("return_code_fields", "error_code_fields"):
        for name in data.get(field, []):
            if isinstance(name, str) and name.strip():
                patterns.append(name.strip().upper())
    return patterns


def extract_entities(
    text: str,
    *,
    known_programs: set[str] | None = None,
    known_codes: set[str] | None = None,
    known_fields: set[str] | None = None,
    rules_path: Path | None = None,
) -> list[ExtractedEntity]:
    if not text.strip():
        return []
    upper = text.upper()
    entities: list[ExtractedEntity] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: str, confidence: float, span: str = "") -> None:
        key = (kind, value.upper())
        if key in seen:
            return
        seen.add(key)
        entities.append(
            ExtractedEntity(kind=kind, value=value, confidence=confidence, span=span[:200])
        )

    if known_codes:
        for code in known_codes:
            if not code:
                continue
            cu = code.upper()
            if len(cu) == 2:
                found = any(m.group(1).upper() == cu for m in _TWO_CHAR_BOUNDARY.finditer(text))
            else:
                found = cu in upper
            if found:
                add("error_code", code, 0.95, _snippet(text, code))

    for m in _TWO_CHAR_CODE_RE.finditer(text):
        add("error_code", m.group(1).upper(), 0.7, m.group(0))

    for m in _QUOTED_CODE_RE.finditer(text):
        val = m.group(1).upper()
        if len(val) <= 8:
            add("error_code", val, 0.6, m.group(0))

    if known_programs:
        for prog in known_programs:
            if prog and prog.upper() in upper:
                add("program_id", prog, 0.9, _snippet(text, prog))

    for m in _PROGRAM_RE.finditer(text):
        val = m.group(1).upper()
        if known_programs is None or val in known_programs:
            conf = 0.85 if known_programs and val in known_programs else 0.5
            add("program_id", val, conf, m.group(0))

    if known_fields:
        from cobol_error_scanner.ingestion.search_terms import field_aliases

        needles: set[str] = set()
        for field in known_fields:
            if field:
                needles.add(field.upper())
                needles.update(field_aliases(field))
        for needle in needles:
            if needle in upper:
                add(
                    "corora_field",
                    needle[:MAX_ERROR_FIELD_INPUT_LEN],
                    0.9,
                    _snippet(text, needle),
                )

    for m in _CORORA_RE.finditer(text):
        val = m.group(1).upper()[:MAX_ERROR_FIELD_INPUT_LEN]
        add("corora_field", val, 0.8, m.group(0))

    for hint in _SYMPTOM_HINTS:
        if hint in upper:
            add("symptom", hint, 0.4, _snippet(text, hint))

    _patterns = load_error_code_patterns(rules_path)
    for pat in _patterns:
        if pat in upper:
            add("symptom", pat, 0.35, _snippet(text, pat))

    return entities


def _candidate_error_codes(text: str) -> set[str]:
    """Raw two-character candidates before _mentions_code validation."""
    candidates: set[str] = set()
    for match in _TWO_CHAR_CODE_RE.finditer(text):
        candidates.add(match.group(1).upper())
    for match in _QUOTED_CODE_RE.finditer(text):
        val = match.group(1).upper()
        if len(val) == 2:
            candidates.add(val)
    return candidates


def extract_mentioned_error_codes(text: str) -> set[str]:
    """Error codes explicitly referenced in document text (scan-independent)."""
    if not text.strip():
        return set()
    mentioned: set[str] = set()
    for code in _candidate_error_codes(text):
        if _mentions_code(text, code):
            mentioned.add(code)
    return mentioned


def _snippet(text: str, needle: str, radius: int = 60) -> str:
    idx = text.upper().find(needle.upper())
    if idx < 0:
        return ""
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    return text[start:end].replace("\n", " ")
