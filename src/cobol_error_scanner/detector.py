"""Detect configured error codes in normalized COBOL lines."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ErrorCodeRule:
    name: str
    pattern: re.Pattern[str]


@dataclass
class DetectorConfig:
    """Field name lists use uppercase; matching is substring / suffix style."""

    return_code_fields: list[str]
    error_code_fields: list[str]
    error_message_fields: list[str]
    rules: list[ErrorCodeRule]
    code_length: int | None = None


def load_detector_config(path: Path) -> DetectorConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    ret = [str(x).upper() for x in data.get("return_code_fields", [])]
    ec = [str(x).upper() for x in data.get("error_code_fields", [])]
    em = [str(x).upper() for x in data.get("error_message_fields", [])]
    rules: list[ErrorCodeRule] = []
    for item in data.get("error_patterns", []):
        rules.append(
            ErrorCodeRule(
                name=item["name"],
                pattern=re.compile(item["regex"], re.IGNORECASE),
            )
        )
    raw_len = data.get("code_length")
    code_length = int(raw_len) if isinstance(raw_len, int) or (isinstance(raw_len, str) and raw_len.isdigit()) else None
    return DetectorConfig(
        return_code_fields=ret,
        error_code_fields=ec,
        error_message_fields=em,
        rules=rules,
        code_length=code_length,
    )


def _matches_field_list(target: str, fields: list[str]) -> bool:
    t = target.upper().replace(" ", "")
    for f in fields:
        f2 = f.replace(" ", "")
        if f2 in t or t.endswith(f2):
            return True
    return False


def is_return_code_field(target: str, cfg: DetectorConfig) -> bool:
    return _matches_field_list(target, cfg.return_code_fields)


def is_error_code_field(target: str, cfg: DetectorConfig) -> bool:
    return _matches_field_list(target, cfg.error_code_fields)


def is_error_message_field(target: str, cfg: DetectorConfig) -> bool:
    return _matches_field_list(target, cfg.error_message_fields)


def is_error_value_target(target: str, cfg: DetectorConfig) -> bool:
    return is_return_code_field(target, cfg) or is_error_code_field(target, cfg)


_MOVE_NUM = re.compile(
    r"\bMOVE\s+(\d+)\s+TO\s+([\w-]+)",
    re.IGNORECASE,
)
_MOVE_QUOTED = re.compile(
    r"\bMOVE\s+(['\"])([^'\"]+)\1\s+TO\s+([\w-]+)",
    re.IGNORECASE,
)
_SET_NUM = re.compile(
    r"\bSET\s+([\w-]+)\s+TO\s+(\d+)",
    re.IGNORECASE,
)


def find_assignments(line: str) -> list[tuple[str, str, str]]:
    """
    Return list of (literal, target_field, kind) for MOVE/SET that look like error assignments.
    kind is 'numeric' or 'alnum'.
    """
    hits: list[tuple[str, str, str]] = []
    for m in _MOVE_NUM.finditer(line):
        hits.append((m.group(1), m.group(2), "numeric"))
    for m in _MOVE_QUOTED.finditer(line):
        hits.append((m.group(2), m.group(3), "alnum"))
    for m in _SET_NUM.finditer(line):
        hits.append((m.group(2), m.group(1), "numeric"))
    return hits


def match_rules_on_line(line: str, cfg: DetectorConfig) -> list[str]:
    return [r.name for r in cfg.rules if r.pattern.search(line)]
