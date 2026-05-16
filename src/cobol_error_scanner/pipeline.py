"""End-to-end scan: files → parse → detect → extract → summarize → manifest."""

from __future__ import annotations

from pathlib import Path

from cobol_error_scanner.cobol_parse import CobolStructureParser, paragraph_for_line
from cobol_error_scanner.detector import (
    DetectorConfig,
    find_assignments,
    is_error_message_field,
    is_error_value_target,
    load_detector_config,
    match_rules_on_line,
)
from cobol_error_scanner.logic_extractor import (
    collect_paths_for_line,
    extract_window,
    find_matching_end_if,
    find_message_literal_in_block,
    find_preceding_if_line,
    identifiers_in_condition,
    parse_if_condition_line,
)
from cobol_error_scanner.models import ErrorOccurrence, ProgramSummary, SourceLocation
from cobol_error_scanner.scanner import iter_cobol_files
from cobol_error_scanner.summarizer import SummarizerConfig, summarize_program, summarize_row


def program_id_from_path(path: Path) -> str:
    return path.stem.upper()


def _paragraph_context(sections, line_no: int) -> tuple[list[str], int, str | None, str | None]:
    sec_name, para_name = paragraph_for_line(sections, line_no)
    para_lines: list[str] = []
    line_in_para = 0
    if para_name:
        for s in sections:
            for p in s.paragraphs:
                if (
                    p.name == para_name
                    and p.start_line <= line_no <= p.end_line
                ):
                    para_lines = p.lines
                    line_in_para = line_no - p.start_line
                    break
    return para_lines, line_in_para, sec_name, para_name


def _enrich_if_block(
    norm: list[str],
    move_idx: int,
    cfg: DetectorConfig,
) -> tuple[str, str, str]:
    """Return (condition, parameters_csv, error_message_literal)."""
    if_idx = find_preceding_if_line(norm, move_idx)
    if if_idx is None:
        return "", "", ""
    cond = parse_if_condition_line(norm[if_idx])
    params = ", ".join(identifiers_in_condition(cond))
    end_if = find_matching_end_if(norm, if_idx)
    if end_if is None:
        return cond, params, ""
    msg = find_message_literal_in_block(
        norm,
        if_idx,
        end_if,
        lambda t: is_error_message_field(t, cfg),
    )
    return cond, params, msg


def scan_root(
    root: Path,
    rules_path: Path,
    *,
    summarizer: SummarizerConfig | None = None,
) -> list[ProgramSummary]:
    cfg: DetectorConfig = load_detector_config(rules_path)
    parser = CobolStructureParser()
    summaries: list[ProgramSummary] = []

    for src in iter_cobol_files(root):
        raw_lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
        norm, sections = parser.parse_lines(raw_lines)
        occs: list[ErrorOccurrence] = []

        for idx, line in enumerate(norm):
            line_no = idx + 1
            rule_hits = match_rules_on_line(line, cfg)
            assigns = find_assignments(line)

            for lit, target, kind in assigns:
                if not is_error_value_target(target, cfg) and not rule_hits:
                    continue
                if cfg.code_length is not None and len(lit) != cfg.code_length:
                    continue
                para_lines, lip, sec, para = _paragraph_context(sections, line_no)
                path_hint = collect_paths_for_line(para_lines, lip) if para_lines else ""
                window, related = extract_window(norm, idx, target_field=target)
                if path_hint:
                    window = path_hint + "\n---\n" + window

                condition, params_txt, msg_lit = _enrich_if_block(norm, idx, cfg)

                occ = ErrorOccurrence(
                    code=lit,
                    literal_kind=kind,
                    location=SourceLocation(path=src, line=line_no),
                    setting_statement=line.strip(),
                    paragraph=para,
                    section=sec,
                    related=related,
                    logic_context=window,
                    condition=condition,
                    parameters_text=params_txt,
                    error_message_literal=msg_lit,
                )
                occ.row_summary = summarize_row(occ)
                occs.append(occ)

            if rule_hits and not assigns:
                para_lines, lip, sec, para = _paragraph_context(sections, line_no)
                path_hint = collect_paths_for_line(para_lines, lip) if para_lines else ""
                window, related = extract_window(norm, idx)
                if path_hint:
                    window = path_hint + "\n---\n" + window
                for name in rule_hits:
                    condition, params_txt, msg_lit = _enrich_if_block(norm, idx, cfg)
                    occ = ErrorOccurrence(
                        code=name,
                        literal_kind="pattern",
                        location=SourceLocation(path=src, line=line_no),
                        setting_statement=line.strip(),
                        paragraph=para,
                        section=sec,
                        related=related,
                        logic_context=window,
                        condition=condition,
                        parameters_text=params_txt,
                        error_message_literal=msg_lit,
                    )
                    occ.row_summary = summarize_row(occ)
                    occs.append(occ)

        search_parts = [program_id_from_path(src), str(src)]
        for o in occs:
            search_parts.append(o.code)
            search_parts.append(o.setting_statement)

        ps = ProgramSummary(
            program_id=program_id_from_path(src),
            source_path=src,
            occurrences=occs,
            search_blob=" ".join(search_parts),
        )
        ps.plain_english = summarize_program(ps, summarizer)
        summaries.append(ps)

    return summaries


def filter_programs_by_error_code(
    programs: list[ProgramSummary],
    error_code: str,
    *,
    summarizer: SummarizerConfig | None = None,
) -> list[ProgramSummary]:
    """
    Keep only occurrences whose ``code`` equals ``error_code`` (case-insensitive).
    Drops programs with no matching findings. Rebuilds per-program summaries.
    """
    needle = error_code.strip().upper()
    if not needle:
        return programs
    out: list[ProgramSummary] = []
    for p in programs:
        occs = [o for o in p.occurrences if o.code.upper() == needle]
        if not occs:
            continue
        q = p.model_copy(update={"occurrences": occs})
        q.plain_english = summarize_program(q, summarizer)
        out.append(q)
    return out
