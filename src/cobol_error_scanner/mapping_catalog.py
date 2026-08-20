"""Load error code ↔ condition-name mappings from copybook-style text files.

Supports the **CORORA**, **CORORL**, and **CORORH** families (``CORORA-R-*``,
``CORORL-R-*``, ``CORORH-R-*``) and parallel mapping filenames under
``error_mapping_files/``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAPPING_FAMILIES = ("CORORA", "CORORL", "CORORH")

#: Regex alternation of the supported mapping families (e.g. ``CORORA|CORORL|CORORH``).
_FAMILY_ALT = "|".join(MAPPING_FAMILIES)

# 88  CORORA-R-ERROR-DOM-TO-INTL-BI   VALUE 'X5'.
# 88 CORORL-R-BAD-RESP-ORP619        VALUE 'C0'.
# 88 CORORH-R-ERROR-SHIP-VIA         VALUE 'V'.
_VALUE_LINE = re.compile(
    rf"\b((?:{_FAMILY_ALT})-R-[\w-]+)\s+VALUE\s+['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MappingFileSet:
    """Resolved paths for CORORA / CORORL / CORORH two-char and one-char fragments."""

    corora_two: Path
    corora_one: Path
    cororl_two: Path
    cororl_one: Path
    cororh_two: Path
    cororh_one: Path

    def two_char_paths(self) -> dict[str, Path]:
        """Map each family to its two-char fragment path (files may be missing)."""
        return {
            "CORORA": self.corora_two,
            "CORORL": self.cororl_two,
            "CORORH": self.cororh_two,
        }

    def one_char_paths(self) -> dict[str, Path]:
        """Map each family to its one-char fragment path (files may be missing)."""
        return {
            "CORORA": self.corora_one,
            "CORORL": self.cororl_one,
            "CORORH": self.cororh_one,
        }


def load_two_char_value_to_names(path: Path) -> dict[str, list[str]]:
    """
    Map two-character literals (e.g. X5) to 88-level condition names
    from a two-character error copybook fragment (CORORA or CORORL).
    """
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, list[str]] = {}
    for m in _VALUE_LINE.finditer(text):
        name = m.group(1).upper()
        val = m.group(2).upper()
        if len(val) != 2:
            continue
        bucket = out.setdefault(val, [])
        if name not in bucket:
            bucket.append(name)
    return out


def load_one_char_error_type_map(path: Path, *, family: str) -> dict[str, str]:
    """
    Map single-character ``VALUE`` to the **first** ``<FAMILY>-R-ERROR-*`` name
    in file order (same first-wins rule as legacy CORORA-only behavior).

    ``family`` must be one of :data:`MAPPING_FAMILIES` (case-insensitive).
    """
    fam = family.strip().upper()
    if fam not in MAPPING_FAMILIES:
        return {}
    prefix = f"{fam}-R-ERROR-"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    cut = text.upper().find("REDEFINES")
    if cut != -1:
        text = text[:cut]
    out: dict[str, str] = {}
    for m in _VALUE_LINE.finditer(text):
        name = m.group(1).upper()
        val = m.group(2).upper()
        if len(val) != 1:
            continue
        if "WARN" in name:
            continue
        if prefix not in name:
            continue
        if val in out:
            continue
        out[val] = name
    return out


def load_corora_one_char_error_type_map(path: Path) -> dict[str, str]:
    """Backward-compatible: CORORA one-char map only."""
    return load_one_char_error_type_map(path, family="CORORA")


def load_one_char_error_flags(path: Path) -> dict[str, str]:
    """Alias for :func:`load_corora_one_char_error_type_map`."""
    return load_corora_one_char_error_type_map(path)


_INV_TRANSIT_MODE = re.compile(
    rf"\b((?:{_FAMILY_ALT})-R-INV-TRANSIT-MODE)\s+VALUE\s+['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


def load_inv_transit_mode_second_char(path: Path, *, family: str) -> str | None:
    """
    Single-character ``VALUE`` of ``<FAMILY>-R-INV-TRANSIT-MODE`` in the one-char
    fragment (e.g. ``J`` for ``EJ`` flows).
    """
    fam = family.strip().upper()
    if fam not in MAPPING_FAMILIES:
        return None
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    cut = text.upper().find("REDEFINES")
    if cut != -1:
        text = text[:cut]
    for m in _INV_TRANSIT_MODE.finditer(text):
        full = m.group(1).upper()
        if not full.startswith(f"{fam}-R-"):
            continue
        val = m.group(2).strip().upper()
        if len(val) == 1:
            return val
    return None


def load_corora_inv_transit_mode_second_char(path: Path) -> str | None:
    """Backward-compatible: CORORA ``INV-TRANSIT-MODE`` only."""
    return load_inv_transit_mode_second_char(path, family="CORORA")


def resolve_mapping_directory(
    source_root: Path,
    explicit: Path | None,
) -> Path | None:
    """Pick a directory containing CORORA_* / CORORL_* / CORORH_* mapping files."""
    if explicit is not None:
        p = explicit.resolve()
        return p if p.is_dir() else None
    candidates = [
        Path("error_mapping_files").resolve(),
        (source_root / "error_mapping_files").resolve(),
        (source_root.parent / "error_mapping_files").resolve(),
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def resolve_corora_mapping_dir(
    source_root: Path,
    explicit: Path | None,
) -> Path | None:
    """Alias for :func:`resolve_mapping_directory` (backward-compatible name)."""
    return resolve_mapping_directory(source_root, explicit)


def _pick_two_one(base: Path, stem: str) -> tuple[Path, Path]:
    two = base / f"{stem}_TWO_CHAR_ERROR.txt"
    if not two.is_file():
        two = base / f"{stem}_TWO_CHAR_ERROR"
    one = base / f"{stem}_ONE_CHAR_ERROR.txt"
    if not one.is_file():
        one = base / f"{stem}_ONE_CHAR_ERROR"
    return two, one


def default_mapping_paths(mapping_dir: Path) -> MappingFileSet:
    """CORORA, CORORL, and CORORH two-char / one-char paths (file may be missing)."""
    c2, c1 = _pick_two_one(mapping_dir, "CORORA")
    l2, l1 = _pick_two_one(mapping_dir, "CORORL")
    h2, h1 = _pick_two_one(mapping_dir, "CORORH")
    return MappingFileSet(
        corora_two=c2,
        corora_one=c1,
        cororl_two=l2,
        cororl_one=l1,
        cororh_two=h2,
        cororh_one=h1,
    )


def default_corora_mapping_paths(mapping_dir: Path) -> tuple[Path, Path]:
    """Backward-compatible: return (CORORA two-char, CORORA one-char) only."""
    m = default_mapping_paths(mapping_dir)
    return m.corora_two, m.corora_one


MAX_ERROR_FIELD_INPUT_LEN = 30

RESERVED_ERROR_FIELD_QUERIES = frozenset(
    {"ERR", "ERROR", "ERROR-", "-ERROR", "-ERROR-"}
)

_RESERVED_KEYWORDS_DISPLAY = "ERR, ERROR, ERROR-, -ERROR, -ERROR-"


def normalize_user_error_field_input(raw: str) -> str:
    """Strip, uppercase, cap length (for search needles)."""
    return raw.strip().upper()[:MAX_ERROR_FIELD_INPUT_LEN]


def _error_field_core_fragment(normalized: str) -> str:
    """Strip any ``<FAMILY>-R-`` prefix before the reserved-keyword check."""
    for fam in MAPPING_FAMILIES:
        prefix = f"{fam}-R-"
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]
    return normalized


def error_field_query_violation(raw: str) -> str | None:
    """Return a user-facing reason if *raw* is a reserved generic keyword, else None."""
    normalized = normalize_user_error_field_input(raw)
    if not normalized:
        return None
    core = _error_field_core_fragment(normalized)
    if normalized in RESERVED_ERROR_FIELD_QUERIES or core in RESERVED_ERROR_FIELD_QUERIES:
        token = core if core in RESERVED_ERROR_FIELD_QUERIES else normalized
        return (
            f"Error field query rejected: {token!r} is too generic for a scan or filter. "
            f"Use a specific 88-level name fragment (e.g. ERR-NO-SEC-EDD-OVRD), "
            f"not a reserved keyword: {_RESERVED_KEYWORDS_DISPLAY}."
        )
    return None


def validate_error_field_query(raw: str) -> str:
    """Normalize; raise ValueError with a specific message if reserved."""
    normalized = normalize_user_error_field_input(raw)
    if not normalized:
        return normalized
    reason = error_field_query_violation(raw)
    if reason:
        raise ValueError(reason)
    return normalized


def canonical_r_field_name(user_fragment: str, *, family: str) -> str:
    """
    Map user fragments like ``ERR-NO-SEC-EDD-OVRD`` to ``CORORA-R-ERR-…`` or
    ``CORORL-R-ERR-…`` when they do not already include that prefix.
    """
    fam = family.strip().upper()
    if fam not in MAPPING_FAMILIES:
        return ""
    prefix = f"{fam}-R-"
    u = normalize_user_error_field_input(user_fragment)
    if not u:
        return ""
    if u.startswith(prefix):
        return u
    return f"{prefix}{u}"


def canonical_corora_r_field_name(user_fragment: str) -> str:
    """Backward-compatible: CORORA canonical name."""
    return canonical_r_field_name(user_fragment, family="CORORA")


def field_search_needles(user_query: str) -> list[str]:
    """
    Substrings for searching 88-level names in mapping files.

    Includes the raw query, ``CORORA-R-`` + query, and ``CORORL-R-`` + query when
    the query does not already include those prefixes.
    """
    u = normalize_user_error_field_input(user_query)
    if not u:
        return []
    out: list[str] = [u]
    for fam in MAPPING_FAMILIES:
        prefix = f"{fam}-R-"
        if u.startswith(prefix):
            suf = u[len(prefix) :].strip()
            if suf:
                out.append(suf)
        else:
            out.append(f"{prefix}{u}")
    seen: set[str] = set()
    uniq: list[str] = []
    for n in out:
        if n and n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def corora_field_search_needles(user_query: str) -> list[str]:
    """Alias for :func:`field_search_needles`."""
    return field_search_needles(user_query)


def find_mapping_rows_matching_field(
    paths: MappingFileSet,
    user_query: str,
    *,
    min_needle_len: int = 2,
) -> list[tuple[str, str, str]]:
    """
    Scan every family's mapping fragments for 88 lines whose condition name
    contains any search needle.

    Returns ``(condition_name, value_literal, file_kind)`` where ``file_kind`` is
    ``two_char_<family>`` or ``one_char_<family>`` with ``<family>`` lowercased
    (e.g. ``two_char_corora``, ``one_char_cororh``).
    """
    needles = field_search_needles(user_query)
    needles = [n for n in needles if len(n) >= min_needle_len]
    if not needles:
        return []

    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def _scan(path: Path, kind: str) -> None:
        if not path.is_file():
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in _VALUE_LINE.finditer(text):
            name = m.group(1).upper()
            val = m.group(2).upper()
            if not any(n in name for n in needles):
                continue
            key = (name, val, kind)
            if key not in seen:
                seen.add(key)
                out.append(key)

    two_paths = paths.two_char_paths()
    one_paths = paths.one_char_paths()
    for fam in MAPPING_FAMILIES:
        fam_key = fam.lower()
        _scan(two_paths[fam], f"two_char_{fam_key}")
        _scan(one_paths[fam], f"one_char_{fam_key}")
    return out


def find_corora_mapping_rows_matching_field(
    two_path: Path,
    one_path: Path,
    user_query: str,
    *,
    min_needle_len: int = 2,
) -> list[tuple[str, str, str]]:
    """
    Backward-compatible: scan only the given CORORA two/one paths (same kinds as
    before: ``two_char``, ``one_char``).
    """
    needles = field_search_needles(user_query)
    needles = [n for n in needles if len(n) >= min_needle_len]
    if not needles:
        return []
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def _scan(path: Path, kind: str) -> None:
        if not path.is_file():
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in _VALUE_LINE.finditer(text):
            name = m.group(1).upper()
            val = m.group(2).upper()
            if not any(n in name for n in needles):
                continue
            key = (name, val, kind)
            if key not in seen:
                seen.add(key)
                out.append(key)

    _scan(two_path, "two_char")
    _scan(one_path, "one_char")
    return out
