"""Resolve two-character error codes using CORORA / CORORL / CORORH mapping files + COBOL rules."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cobol_error_scanner.cobol_parse import (
    CobolStructureParser,
    paragraph_for_line,
    paragraph_start_line_for_source_line,
)
from cobol_error_scanner.mapping_catalog import (
    MAPPING_FAMILIES,
    MappingFileSet,
    default_mapping_paths,
    find_mapping_rows_matching_field,
    load_inv_transit_mode_second_char,
    load_one_char_error_type_map,
    load_two_char_value_to_names,
    normalize_user_error_field_input,
    resolve_mapping_directory,
    validate_error_field_query,
)

#: Regex alternation of the supported mapping families (e.g. ``CORORA|CORORL|CORORH``).
_FAMILY_ALT = "|".join(MAPPING_FAMILIES)
from cobol_error_scanner.logic_extractor import enrich_corora_occurrence_control_flow
from cobol_error_scanner.models import ErrorOccurrence, ProgramSummary, SourceLocation
from cobol_error_scanner.scanner import iter_cobol_files
from cobol_error_scanner.summarizer import SummarizerConfig, summarize_program, summarize_row


def _ignore_line(line: str) -> bool:
    return "WS-ERROR-SW" in line.upper()


def _program_id_from_path(path: Path) -> str:
    return path.stem.upper()


_SET_TO_TRUE = re.compile(
    r"\bSET\s+([\w-]+)\s+TO\s+TRUE\b",
    re.IGNORECASE,
)
_MOVE_W_TO_RECORD_RESPONSE_FLAG = re.compile(
    rf"\bMOVE\s+['\"]W['\"]\s+TO\s+({_FAMILY_ALT})-R-RECORD-RESPONSE-FLAG\b",
    re.IGNORECASE,
)


def _family_from_error_type_receiver(tok: str) -> str:
    t = (tok or "").upper()
    for fam in MAPPING_FAMILIES:
        if f"{fam}-R-ERROR-TYPE" in t or t.startswith(f"{fam}-"):
            return fam
    return "CORORA"


def _lines_of_paragraph_containing_line(sections, line_no: int) -> list[str] | None:
    for sec in sections:
        for para in sec.paragraphs:
            if para.start_line <= line_no <= para.end_line:
                return para.lines
    return None


def _enrich_control_flow_in_paragraph(
    occ: ErrorOccurrence,
    norm: list[str],
    sections,
    line_no: int,
) -> None:
    ps = paragraph_start_line_for_source_line(sections, line_no)
    enrich_corora_occurrence_control_flow(
        occ, norm, paragraph_start_line=ps
    )


def _paragraph_moves_w_to_record_response_flag(paragraph_lines: list[str]) -> bool:
    """True if paragraph moves W to either CORORA- or CORORL- response flag."""
    for ln in paragraph_lines:
        if _ignore_line(ln):
            continue
        if _MOVE_W_TO_RECORD_RESPONSE_FLAG.search(ln):
            return True
    return False


def _paragraph_moves_w_for_target_family(paragraph_lines: list[str], family: str) -> bool:
    """W-move to ``<FAMILY>-R-RECORD-RESPONSE-FLAG`` only."""
    fam = family.upper()
    pat = re.compile(
        rf"\bMOVE\s+['\"]W['\"]\s+TO\s+{re.escape(fam)}-R-RECORD-RESPONSE-FLAG\b",
        re.IGNORECASE,
    )
    for ln in paragraph_lines:
        if _ignore_line(ln):
            continue
        if pat.search(ln):
            return True
    return False


def _scan_e_prefix_move_error_type_with_w_paragraph_rule(
    root: Path,
    *,
    code: str,
    second: str,
    primary: str | None,
    resolution_note: str,
    target_family: str | None = None,
) -> dict[str, list[ErrorOccurrence]]:
    """
    ``MOVE '<2nd>' TO <FAMILY>-R-ERROR-TYPE`` when the paragraph does not also
    contain ``MOVE 'W' TO <same FAMILY>-R-RECORD-RESPONSE-FLAG``.

    If ``target_family`` is None, match either CORORA or CORORL and use the
    matched line's family for the W-move exclusion.
    """
    if target_family:
        move_pat = re.compile(
            rf"\bMOVE\s+['\"]{re.escape(second)}['\"]\s+TO\s+{re.escape(target_family.upper())}-R-ERROR-TYPE\b",
            re.IGNORECASE,
        )
    else:
        move_pat = re.compile(
            rf"\bMOVE\s+['\"]{re.escape(second)}['\"]\s+TO\s+((?:{_FAMILY_ALT})-R-ERROR-TYPE)\b",
            re.IGNORECASE,
        )
    ef = (primary or "").strip()
    parser = CobolStructureParser()
    by_file: dict[str, list[ErrorOccurrence]] = {}
    first_excluded: tuple[Path, int, str, Any, str] | None = None

    for src in iter_cobol_files(root):
        key = str(src.resolve())
        raw_lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
        norm, sections = parser.parse_lines(raw_lines)
        for idx, line in enumerate(norm):
            if _ignore_line(line):
                continue
            m = move_pat.search(line)
            if not m:
                continue
            if target_family:
                fam = target_family.upper()
            elif m.lastindex and m.group(1):
                fam = _family_from_error_type_receiver(m.group(1))
            else:
                fam = "CORORA"
            line_no = idx + 1
            para_lines = _lines_of_paragraph_containing_line(sections, line_no)
            if para_lines and _paragraph_moves_w_for_target_family(para_lines, fam):
                if first_excluded is None:
                    first_excluded = (src, line_no, line.strip(), sections, fam)
                continue
            receiver = (m.group(1).strip() if (m.lastindex and m.group(1)) else "")
            occ = _make_occurrence(
                code=code,
                src=src,
                line_no=line_no,
                statement=line.strip(),
                sections=sections,
                resolution_note=resolution_note,
                error_field=ef or receiver or f"{fam}-R-ERROR-TYPE",
            )
            _enrich_control_flow_in_paragraph(occ, norm, sections, line_no)
            by_file.setdefault(key, []).append(occ)

    if by_file:
        return by_file

    if first_excluded is None:
        return {}

    src, line_no, stmt, sections, excl_fam = first_excluded
    note_ph = (
        f"{resolution_note} | Disqualified: same paragraph contains "
        f"MOVE 'W' to {excl_fam}-R-RECORD-RESPONSE-FLAG (e.g. warning / response path)."
    )
    occ = _make_occurrence(
        code=code,
        src=src,
        line_no=line_no,
        statement=stmt,
        sections=sections,
        resolution_note=note_ph,
        error_field=ef,
    )
    _enrich_control_flow_in_paragraph(occ, norm, sections, line_no)
    occ.location = SourceLocation(path=occ.location.path, line=0, column=0)
    occ.paragraph = "not found"
    occ.related = []
    occ.condition = "Logic not found"
    occ.row_summary = "Logic not found"
    return {str(src.resolve()): [occ]}


def _merge_occurrence_dicts(
    a: dict[str, list[ErrorOccurrence]],
    b: dict[str, list[ErrorOccurrence]],
) -> dict[str, list[ErrorOccurrence]]:
    out: dict[str, list[ErrorOccurrence]] = {k: list(v) for k, v in a.items()}
    for k, v in b.items():
        out.setdefault(k, []).extend(v)
    return out


def _scan_move_error_type_inv_transit_branch(
    root: Path,
    *,
    code: str,
    second: str,
    one_path: Path,
    family: str,
) -> dict[str, list[ErrorOccurrence]]:
    """INV-TRANSIT-MODE branch for CORORA or CORORL namespace."""
    fam = family.upper()
    inv_name = f"{fam}-R-INV-TRANSIT-MODE"
    move_pat = re.compile(
        rf"\bMOVE\s+['\"]{re.escape(second)}['\"]\s+TO\s+{re.escape(fam)}-R-ERROR-TYPE\b",
        re.IGNORECASE,
    )
    note_move_ok = (
        f"E-prefix {code}: MOVE '{second}' TO {fam}-R-ERROR-TYPE "
        f"(same paragraph has no MOVE 'W' TO {fam}-R-RECORD-RESPONSE-FLAG; "
        f"{one_path.name} INV-TRANSIT / {fam})"
    )
    parser = CobolStructureParser()
    by_file: dict[str, list[ErrorOccurrence]] = {}
    for src in iter_cobol_files(root):
        key = str(src.resolve())
        raw_lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
        norm, sections = parser.parse_lines(raw_lines)
        for idx, line in enumerate(norm):
            if _ignore_line(line):
                continue
            if not move_pat.search(line):
                continue
            line_no = idx + 1
            para_lines = _lines_of_paragraph_containing_line(sections, line_no)
            if para_lines and _paragraph_moves_w_for_target_family(para_lines, fam):
                continue
            occ = _make_occurrence(
                code=code,
                src=src,
                line_no=line_no,
                statement=line.strip(),
                sections=sections,
                resolution_note=note_move_ok,
                error_field=inv_name,
            )
            _enrich_control_flow_in_paragraph(occ, norm, sections, line_no)
            by_file.setdefault(key, []).append(occ)

    note_set = (
        f"E-prefix {code}: {one_path.name} → SET {inv_name} TO TRUE "
        f"(INV-TRANSIT / ERROR-TYPE branch for 2nd char '{second}' / {fam})"
    )
    set_hits = _scan_set_true_for_names(
        root,
        code=code,
        names=[inv_name],
        resolution_note=note_set,
    )
    return _merge_occurrence_dicts(by_file, set_hits)


def _paragraph_context(
    sections, line_no: int
) -> tuple[str | None, str | None]:
    return paragraph_for_line(sections, line_no)


def _make_occurrence(
    *,
    code: str,
    src: Path,
    line_no: int,
    statement: str,
    sections,
    resolution_note: str,
    error_field: str = "",
    mapping_detail: str = "",
) -> ErrorOccurrence:
    sec, para = _paragraph_context(sections, line_no)
    ef = (error_field or "").strip()
    occ = ErrorOccurrence(
        code=code,
        literal_kind="alnum",
        location=SourceLocation(path=src, line=line_no),
        setting_statement=statement.strip(),
        paragraph=para,
        section=sec,
        logic_context=resolution_note,
        condition="",
        parameters_text="",
        error_message_literal="",
        error_field=ef,
        mapping_detail=(mapping_detail or "").strip(),
    )
    occ.row_summary = summarize_row(occ)
    if ef:
        occ.row_summary = ef
    if occ.mapping_detail and occ.mapping_detail not in (occ.row_summary or ""):
        occ.row_summary = f"{occ.row_summary} — {occ.mapping_detail}".strip(" —")
    return occ


def _scan_files_for_pattern(
    root: Path,
    *,
    code: str,
    pattern: re.Pattern[str],
    resolution_note: str,
    error_field: str = "",
    mapping_detail: str = "",
) -> dict[str, list[ErrorOccurrence]]:
    parser = CobolStructureParser()
    by_file: dict[str, list[ErrorOccurrence]] = {}
    for src in iter_cobol_files(root):
        key = str(src.resolve())
        raw_lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
        norm, sections = parser.parse_lines(raw_lines)
        for idx, line in enumerate(norm):
            if _ignore_line(line):
                continue
            if not pattern.search(line):
                continue
            line_no = idx + 1
            occ = _make_occurrence(
                code=code,
                src=src,
                line_no=line_no,
                statement=line.strip(),
                sections=sections,
                resolution_note=resolution_note,
                error_field=error_field,
                mapping_detail=mapping_detail,
            )
            _enrich_control_flow_in_paragraph(occ, norm, sections, line_no)
            by_file.setdefault(key, []).append(occ)
    return by_file


def _set_true_flag_on_line(line: str, next_line: str | None) -> str | None:
    m = _SET_TO_TRUE.search(line)
    if m:
        return m.group(1).upper()
    if not next_line:
        return None
    if "TRUE" in line.upper():
        return None
    m_start = re.search(r"\bSET\s+([\w-]+)\s*\.?\s*$", line.rstrip(), re.IGNORECASE)
    if not m_start:
        return None
    blob = line + " " + next_line
    m2 = _SET_TO_TRUE.search(blob)
    if m2:
        return m2.group(1).upper()
    return None


def _scan_set_true_for_names(
    root: Path,
    *,
    code: str,
    names: list[str],
    resolution_note: str,
    mapping_detail: str = "",
) -> dict[str, list[ErrorOccurrence]]:
    if not names:
        return {}
    name_u = {n.upper() for n in names}
    parser = CobolStructureParser()
    by_file: dict[str, list[ErrorOccurrence]] = {}
    for src in iter_cobol_files(root):
        key = str(src.resolve())
        raw_lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
        norm, sections = parser.parse_lines(raw_lines)
        for idx, line in enumerate(norm):
            if _ignore_line(line):
                continue
            nxt = norm[idx + 1] if idx + 1 < len(norm) else None
            flag = _set_true_flag_on_line(line, nxt)
            if not flag or flag not in name_u:
                continue
            stmt = line.strip()
            if nxt and not _SET_TO_TRUE.search(line) and _SET_TO_TRUE.search(
                line + " " + nxt
            ):
                stmt = (line.rstrip() + " " + nxt.strip()).strip()
            line_no = idx + 1
            occ = _make_occurrence(
                code=code,
                src=src,
                line_no=line_no,
                statement=stmt,
                sections=sections,
                resolution_note=resolution_note,
                error_field=flag,
                mapping_detail=mapping_detail,
            )
            _enrich_control_flow_in_paragraph(occ, norm, sections, line_no)
            by_file.setdefault(key, []).append(occ)
    return by_file


def _two_char_mapping_detail(
    needle: str,
    two_maps: dict[str, dict[str, list[str]]],
) -> str:
    """Describe which families define ``needle`` and their condition names."""
    present = {
        fam: two_maps.get(fam, {}).get(needle, [])
        for fam in MAPPING_FAMILIES
        if two_maps.get(fam, {}).get(needle)
    }
    if not present:
        return ""
    if len(present) == 1:
        (fam, names), = present.items()
        return f"{fam} two-char mapping for {needle}: {', '.join(names)}"
    families = " and ".join(present.keys())
    detail = "; ".join(f"{fam}={', '.join(names)}" for fam, names in present.items())
    return f"Matched in {families} for code {needle}: {detail}"


def _e_prefix_one_char_detail(
    second: str,
    one_maps: dict[str, dict[str, str]],
) -> str:
    """Describe which families map the E-prefix second char, when more than one does."""
    present = {
        fam: one_maps.get(fam, {}).get(second)
        for fam in MAPPING_FAMILIES
        if one_maps.get(fam, {}).get(second)
    }
    if len(present) <= 1:
        return ""
    distinct = set(present.values())
    if len(distinct) == 1:
        return (
            f"E-prefix 2nd char '{second}': same name in "
            f"{len(present)} families ({next(iter(distinct))})"
        )
    parts = "; ".join(f"{fam} → {name}" for fam, name in present.items())
    return f"E-prefix 2nd char '{second}': {parts}"


def _resolve_e_prefix_two_char_code(
    source_root: Path,
    *,
    needle: str,
    paths: MappingFileSet,
    one_maps: dict[str, dict[str, str]],
) -> dict[str, list[ErrorOccurrence]]:
    second = needle[1]
    names: list[str] = []
    seen: set[str] = set()
    for fam in MAPPING_FAMILIES:
        n = one_maps.get(fam, {}).get(second)
        if n and n not in seen:
            seen.add(n)
            names.append(n)

    e_detail = _e_prefix_one_char_detail(second, one_maps)

    note_set = (
        f"E-prefix {needle}: 2nd char '{second}' → one-char maps → "
        f"{names or '(none)'} → SET … TO TRUE"
    )
    hits = _scan_set_true_for_names(
        source_root,
        code=needle,
        names=names,
        resolution_note=note_set,
        mapping_detail=e_detail,
    )
    if hits:
        return hits

    chunks: list[dict[str, list[ErrorOccurrence]]] = []
    for fam, one_path in paths.one_char_paths().items():
        if not one_path.is_file():
            continue
        inv = load_inv_transit_mode_second_char(one_path, family=fam)
        if inv is not None and second == inv:
            chunks.append(
                _scan_move_error_type_inv_transit_branch(
                    source_root,
                    code=needle,
                    second=second,
                    one_path=one_path,
                    family=fam,
                )
            )
    if chunks:
        merged: dict[str, list[ErrorOccurrence]] = {}
        for ch in chunks:
            for k, v in ch.items():
                merged.setdefault(k, []).extend(v)
        for occs in merged.values():
            for o in occs:
                if e_detail and not o.mapping_detail:
                    o.mapping_detail = e_detail
                    if e_detail not in (o.row_summary or ""):
                        o.row_summary = f"{o.row_summary} — {e_detail}".strip(" —")
        return merged

    note_move = (
        f"E-prefix {needle}: no SET for mapped name(s) {names}; "
        f"fallback: MOVE '{second}' to CORORA- or CORORL-R-ERROR-TYPE "
        f"(per-line family; W/RECORD-RESPONSE exclusion per family)"
    )
    out_move = _scan_e_prefix_move_error_type_with_w_paragraph_rule(
        source_root,
        code=needle,
        second=second,
        primary=names[0] if names else None,
        resolution_note=note_move,
        target_family=None,
    )
    if e_detail:
        for vs in out_move.values():
            for o in vs:
                if not o.mapping_detail:
                    o.mapping_detail = e_detail
                    if e_detail not in (o.row_summary or ""):
                        o.row_summary = f"{o.row_summary} — {e_detail}".strip(" —")
    return out_move


def _merge_by_file(
    chunks: list[dict[str, list[ErrorOccurrence]]],
) -> list[ProgramSummary]:
    merged: dict[str, list[ErrorOccurrence]] = {}
    for ch in chunks:
        for path_key, occs in ch.items():
            merged.setdefault(path_key, []).extend(occs)
    out: list[ProgramSummary] = []
    for path_key, occs in sorted(merged.items()):
        occs.sort(key=lambda o: o.location.line)
        path = Path(path_key)
        pid = _program_id_from_path(path)
        ps = ProgramSummary(
            program_id=pid,
            source_path=path,
            occurrences=occs,
            search_blob=" ".join([pid, path_key] + [o.code for o in occs]),
        )
        out.append(ps)
    return out


def resolve_mapped_error_code(
    source_root: Path,
    error_code: str,
    *,
    mapping_dir_explicit: Path | None = None,
) -> list[ProgramSummary]:
    """
    Apply CORORA / CORORL / CORORH mapping rules for a two-character ``error_code``.

    Non-``E`` prefix: resolve literals in **every** family's two-char mapping file,
    merge condition names, and search ``SET <name> TO TRUE``. When more than one
    family defines the same code, :attr:`ErrorOccurrence.mapping_detail` records that.

    Leading ``E``: second character maps via each present one-char file
    (``CORORA_ONE_CHAR_ERROR``, ``CORORL_ONE_CHAR_ERROR``, ``CORORH_ONE_CHAR_ERROR``);
    all mapped ``<FAMILY>-R-ERROR-*`` names are searched for ``SET … TO TRUE``, then
    INV-TRANSIT branches per family, then ``MOVE`` to ``<FAMILY>-R-ERROR-TYPE`` with
    the matching family's ``MOVE 'W' TO <FAMILY>-R-RECORD-RESPONSE-FLAG`` exclusion.
    """
    needle = error_code.strip().upper()
    if len(needle) != 2:
        return []

    mapping_dir = resolve_mapping_directory(source_root, mapping_dir_explicit)
    if mapping_dir is None:
        return []

    paths = default_mapping_paths(mapping_dir)
    two_maps: dict[str, dict[str, list[str]]] = {
        fam: load_two_char_value_to_names(path)
        for fam, path in paths.two_char_paths().items()
    }
    one_maps: dict[str, dict[str, str]] = {
        fam: (
            load_one_char_error_type_map(path, family=fam)
            if path.is_file()
            else {}
        )
        for fam, path in paths.one_char_paths().items()
    }

    chunks: list[dict[str, list[ErrorOccurrence]]] = []

    if needle.startswith("E"):
        chunks.append(
            _resolve_e_prefix_two_char_code(
                source_root,
                needle=needle,
                paths=paths,
                one_maps=one_maps,
            )
        )
        return _programs_from_chunks(chunks)

    names: list[str] = []
    seen_n: set[str] = set()
    for fam in MAPPING_FAMILIES:
        for n in two_maps.get(fam, {}).get(needle, []):
            if n not in seen_n:
                seen_n.add(n)
                names.append(n)

    md = _two_char_mapping_detail(needle, two_maps)
    two_char_names = [p.name for p in paths.two_char_paths().values() if p.is_file()]
    note_set = (
        f"Mapping: {' + '.join(two_char_names) or '(none)'} → "
        f"SET … TO TRUE ({len(names)} condition name(s))"
    )
    chunks.append(
        _scan_set_true_for_names(
            source_root,
            code=needle,
            names=names,
            resolution_note=note_set,
            mapping_detail=md,
        )
    )
    return _programs_from_chunks(chunks)


def _programs_from_chunks(
    chunks: list[dict[str, list[ErrorOccurrence]]],
) -> list[ProgramSummary]:
    programs = _merge_by_file(chunks)
    for p in programs:
        p.plain_english = summarize_program(p, None)
        parts: list[str] = [p.program_id, str(p.source_path)]
        for o in p.occurrences:
            parts.extend(
                [
                    o.code,
                    o.error_field,
                    o.setting_statement,
                    o.condition,
                    o.row_summary,
                    o.mapping_detail,
                ]
            )
        p.search_blob = " ".join(parts)
    return [p for p in programs if p.occurrences]


def _dedupe_occurrences(occs: list[ErrorOccurrence]) -> list[ErrorOccurrence]:
    seen: set[tuple[str, int, str, str]] = set()
    out: list[ErrorOccurrence] = []
    for o in occs:
        p = str(o.location.path.resolve())
        stmt = (o.setting_statement or "")[:240]
        key = (p, int(o.location.line or 0), (o.code or "").upper(), stmt)
        if key in seen:
            continue
        seen.add(key)
        out.append(o)
    return out


def _occ_matches_field_names(o: ErrorOccurrence, matched_names: set[str]) -> bool:
    if not matched_names:
        return True
    ef = (o.error_field or "").upper()
    if ef and ef in matched_names:
        return True
    st = (o.setting_statement or "").upper()
    return any(n in st for n in matched_names)


def resolve_mapped_error_field(
    source_root: Path,
    error_field_query: str,
    *,
    mapping_dir_explicit: Path | None = None,
    summarizer: SummarizerConfig | None = None,
) -> list[ProgramSummary]:
    """
    Resolve by **Error field** substring against CORORA, CORORL, and CORORH mapping
    files, then run the same COBOL resolution as :func:`resolve_mapped_error_code`
    for each derived two-character code.
    """
    q = validate_error_field_query(error_field_query)
    if len(q) < 2:
        return []

    mapping_dir = resolve_mapping_directory(source_root, mapping_dir_explicit)
    if mapping_dir is None:
        return []

    paths = default_mapping_paths(mapping_dir)
    rows = find_mapping_rows_matching_field(paths, q)
    if not rows:
        return []

    matched_names = {r[0] for r in rows}
    codes: set[str] = set()
    for _name, val, kind in rows:
        if kind.startswith("two_char") and len(val) == 2:
            codes.add(val)
        elif kind.startswith("one_char") and len(val) == 1:
            codes.add("E" + val)

    if not codes:
        return []

    families_matched: set[str] = set()
    for _name, _val, kind in rows:
        fam = kind.rsplit("_char_", 1)[-1].upper()
        if fam in MAPPING_FAMILIES:
            families_matched.add(fam)
    field_md = ""
    if len(families_matched) > 1:
        ordered = [f for f in MAPPING_FAMILIES if f in families_matched]
        field_md = (
            "Field search matched rows in multiple mapping families: "
            f"{', '.join(ordered)}."
        )

    merged: dict[str, list[ErrorOccurrence]] = {}
    for code in sorted(codes):
        for ps in resolve_mapped_error_code(
            source_root, code, mapping_dir_explicit=mapping_dir_explicit
        ):
            key = str(ps.source_path.resolve())
            merged.setdefault(key, []).extend(ps.occurrences)

    cfg = summarizer or SummarizerConfig()
    out: list[ProgramSummary] = []
    for path_key in sorted(merged.keys()):
        occs = _dedupe_occurrences(merged[path_key])
        occs = [o for o in occs if _occ_matches_field_names(o, matched_names)]
        if not occs:
            continue
        if field_md:
            for o in occs:
                if field_md not in (o.mapping_detail or ""):
                    o.mapping_detail = (
                        f"{o.mapping_detail}; {field_md}".strip("; ")
                        if o.mapping_detail
                        else field_md
                    )
        path = Path(path_key)
        pid = _program_id_from_path(path)
        ps = ProgramSummary(
            program_id=pid,
            source_path=path,
            occurrences=sorted(occs, key=lambda o: o.location.line),
            search_blob=" ".join([pid, path_key] + [o.code for o in occs]),
        )
        ps.plain_english = summarize_program(ps, cfg)
        parts: list[str] = [ps.program_id, str(ps.source_path), q]
        for o in occs:
            parts.extend(
                [
                    o.code,
                    o.error_field,
                    o.setting_statement,
                    o.condition,
                    o.row_summary,
                    o.mapping_detail,
                ]
            )
        ps.search_blob = " ".join(parts)
        out.append(ps)

    return [p for p in out if p.occurrences]


def apply_mapping_filter_fallback(
    source_root: Path,
    error_code: str,
    *,
    mapping_dir: Path | None = None,
    summarizer: SummarizerConfig | None = None,
) -> list[ProgramSummary]:
    """When standard error-code filtering finds nothing, try mapping rules."""
    resolved = resolve_mapped_error_code(
        source_root, error_code, mapping_dir_explicit=mapping_dir
    )
    if not resolved:
        return []
    cfg = summarizer or SummarizerConfig()
    for p in resolved:
        p.plain_english = summarize_program(p, cfg)
    return resolved


# Backward-compatible aliases (older import paths / names).
resolve_corora_error_code = resolve_mapped_error_code
resolve_corora_error_field = resolve_mapped_error_field
apply_corora_filter_fallback = apply_mapping_filter_fallback
