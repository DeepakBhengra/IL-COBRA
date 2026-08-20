"""Extract local control-flow context around error-setting statements."""

from __future__ import annotations

import re
from collections import deque

from cobol_error_scanner.detector import find_assignments
from cobol_error_scanner.models import ErrorOccurrence, VariableRef


_IDENTIFIER = re.compile(r"\b[A-Z][A-Z0-9-]*\b", re.IGNORECASE)

# Statement starts in the IF body (not valid inside a continued predicate).
_STMT_START = re.compile(
    r"^\s*\b(END-IF|ELSE|SET|MOVE|MULTIPLY|DIVIDE|COMPUTE|PERFORM|GO\s+TO|"
    r"EXIT\s+PROGRAM|STOP\s+RUN|CONTINUE|EXIT|DISPLAY)\b",
    re.IGNORECASE,
)


def _line_counts_as_comment(line: str) -> bool:
    """Fixed-format area or trimmed body starts with COBOL comment marker."""
    s = line.rstrip()
    if len(s) > 6 and s[6:7] == "*":
        return True
    t = s.strip()
    return t.startswith("*") or t.startswith("*>")


def _if_end_counts(line: str) -> tuple[int, int]:
    """Count IF / END-IF tokens; mask END-IF so inner ``IF`` is not double-counted."""
    if _line_counts_as_comment(line):
        return 0, 0
    u = line.upper()
    n_end = len(re.findall(r"\bEND-IF\b", u))
    u2 = re.sub(r"\bEND-IF\b", "      ", u)
    n_if = len(re.findall(r"\bIF\b", u2))
    return n_if, n_end


def _ends_cobol_sentence(line: str) -> bool:
    """True if *line* terminates a COBOL sentence (trailing period in code area)."""
    if _line_counts_as_comment(line):
        return False
    return line.rstrip().endswith(".")


def find_preceding_if_line(lines: list[str], move_idx: int) -> int | None:
    """
    Given a 0-based line index of a statement inside an IF/END-IF block, return the line index
    of the IF that most tightly encloses that statement, or None.

    A COBOL period terminates the current sentence and closes any still-open ``IF``
    scopes, so when the backward scan reaches a sentence-terminating period at the
    same nesting level (before finding an enclosing ``IF``), the statement is not
    inside that earlier ``IF`` and ``None`` is returned. This avoids attaching
    period-terminated ``IF`` statements from a previous sentence.
    """
    nest = 0
    for i in range(move_idx - 1, -1, -1):
        n_if, n_end = _if_end_counts(lines[i])
        nest += n_end - n_if
        if nest < 0:
            return i
        if nest == 0 and _ends_cobol_sentence(lines[i]):
            return None
    return None


def find_matching_end_if(lines: list[str], if_idx: int) -> int | None:
    """Return 0-based index of the END-IF that closes the IF at ``if_idx``, or None."""
    if if_idx < 0 or if_idx >= len(lines):
        return None
    nest = 0
    for j in range(if_idx, len(lines)):
        n_if, n_end = _if_end_counts(lines[j])
        nest += n_if - n_end
        if nest == 0:
            return j
    return None


_ELSE_LINE = re.compile(r"^\s*ELSE\b", re.IGNORECASE)


def if_branch_for_line(lines: list[str], if_idx: int, target_idx: int) -> str:
    """
    Decide whether ``target_idx`` (0-based) sits in the THEN or ELSE branch of the
    ``IF`` at ``if_idx``.

    Returns ``"then"`` when the statement is reached while the condition is TRUE
    (the IF body before any ``ELSE``), or ``"else"`` when it is reached via the
    IF's ``ELSE`` branch. Plain ``IF … END-IF`` blocks (no ``ELSE``) are ``"then"``.
    """
    end_idx = find_matching_end_if(lines, if_idx)
    if end_idx is None:
        end_idx = len(lines)
    inner = 0
    for j in range(if_idx + 1, end_idx):
        line = lines[j]
        if _line_counts_as_comment(line):
            continue
        # An ELSE encountered at the immediate nesting level belongs to this IF.
        if inner == 0 and _ELSE_LINE.match(line):
            return "then" if target_idx < j else "else"
        n_if, n_end = _if_end_counts(line)
        inner += n_if - n_end
        if inner < 0:
            break
    return "then"


_IF_HEADER = re.compile(r"^\s*IF\s+(.+?)\s*(?:THEN)?\s*\.?\s*$", re.IGNORECASE)


def parse_if_condition_line(line: str) -> str:
    """Return the predicate portion of a single-line IF (best-effort)."""
    s = line.strip()
    m = _IF_HEADER.match(s)
    if m:
        return m.group(1).strip().rstrip(".")
    u = s.upper()
    if u.startswith("IF "):
        rest = s[3:].strip()
        if rest.upper().endswith(" THEN"):
            rest = rest[:-5].strip()
        return rest.rstrip(".")
    return s


def identifiers_in_condition(condition: str) -> list[str]:
    """Data names referenced in a condition (figuratives / reserved words removed)."""
    skip = {
        "SPACES",
        "SPACE",
        "ZERO",
        "ZEROS",
        "ZEROES",
        "LOW-VALUE",
        "LOW-VALUES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "QUOTE",
        "QUOTES",
        "NULL",
        "TRUE",
        "FALSE",
        "NOT",
        "AND",
        "OR",
        "TO",
        "IS",
        "ARE",
        "GREATER",
        "LESS",
        "EQUAL",
        "THAN",
        "NOT",
        "NUMERIC",
        "ALPHABETIC",
        "POSITIVE",
        "NEGATIVE",
        "IF",
    }
    out: list[str] = []
    seen: set[str] = set()
    for m in _IDENTIFIER.finditer(condition):
        w = m.group(0).upper()
        if w in skip or len(w) < 2:
            continue
        if len(w) == 2 and w.isalpha():
            continue
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def find_message_literal_in_block(
    lines: list[str],
    if_idx: int,
    end_if_idx: int,
    is_message_field,
) -> str:
    """Scan IF body (lines after IF through line before matching END-IF)."""
    for j in range(if_idx + 1, end_if_idx):
        for lit, target, kind in find_assignments(lines[j]):
            if kind == "alnum" and is_message_field(target):
                return lit
    return ""


def _identifiers_in(line: str, *, skip: set[str]) -> list[str]:
    out: list[str] = []
    for m in _IDENTIFIER.finditer(line):
        w = m.group(0).upper()
        if w in skip or len(w) < 2:
            continue
        keywords = {
            "MOVE",
            "TO",
            "IF",
            "ELSE",
            "END-IF",
            "PERFORM",
            "THRU",
            "THROUGH",
            "UNTIL",
            "VARYING",
            "SET",
            "NOT",
            "AND",
            "OR",
            "THEN",
            "WHEN",
            "END-PERFORM",
            "DISPLAY",
            "STOP",
            "RUN",
            "GOBACK",
            "EXIT",
            "SECTION",
            "DIVISION",
            "PROGRAM-ID",
            "WORKING-STORAGE",
            "LINKAGE",
            "PIC",
            "PICTURE",
            "COMP",
            "VALUE",
        }
        if w in keywords:
            continue
        out.append(w)
    return out


def extract_window(
    lines: list[str],
    center_index: int,
    *,
    before: int = 12,
    after: int = 8,
    target_field: str | None = None,
) -> tuple[str, list[VariableRef]]:
    """
    Return a plain-text window around center_index (0-based) and variable refs.
    """
    lo = max(0, center_index - before)
    hi = min(len(lines), center_index + after + 1)
    window = lines[lo:hi]
    blob_lines: list[str] = []
    related: list[VariableRef] = []
    skip = {target_field.upper()} if target_field else set()

    for i, ln in enumerate(window, start=lo + 1):
        blob_lines.append(f"L{i:05d}: {ln}")
        if lo <= center_index < hi and i - 1 == center_index:
            for name in _identifiers_in(ln, skip=skip):
                role = "near_error_set"
                if target_field and name.upper() != target_field.upper():
                    role = "same_line"
                related.append(VariableRef(name=name, role=role, line=i))

    return "\n".join(blob_lines), related


def extend_if_predicate(lines: list[str], if_idx: int, limit_idx: int) -> str:
    """
    Merge a possibly multi-line IF predicate starting at ``if_idx``.

    Continuation lines are included until ``limit_idx`` (exclusive), a nested
    ``IF``, ``ELSE`` / ``END-IF``, or a new executable statement (``SET``,
    ``MOVE``, ``PERFORM``, …).
    """
    if if_idx < 0 or if_idx >= len(lines):
        return ""
    first = parse_if_condition_line(lines[if_idx])
    parts: list[str] = [first] if first else []
    j = if_idx + 1
    while j < len(lines) and j < limit_idx:
        raw = lines[j]
        s = raw.strip()
        su = s.upper()
        if not s or su.startswith("*"):
            j += 1
            continue
        if _STMT_START.match(raw):
            break
        if su.startswith("END-IF") or su.startswith("ELSE"):
            break
        if re.match(r"^\s*IF\s+", raw, re.IGNORECASE) and not su.startswith("END-IF"):
            break
        parts.append(s)
        j += 1
    return " ".join(parts).strip()


def collect_enclosing_if_predicates(
    lines: list[str],
    set_line_1based: int,
    *,
    max_depth: int = 16,
    max_upward_lines: int = 100,
    min_if_line_1based: int | None = None,
) -> list[str]:
    """
    IF predicates from **innermost** to **outermost** that enclose ``set_line_1based``.

    Stops after ``max_depth`` levels or when the next enclosing ``IF`` is more than
    ``max_upward_lines`` source lines above the error (avoids pulling in unrelated
    outer procedure structure in large programs).

    If ``min_if_line_1based`` is set, ignore any enclosing ``IF`` whose header line is
    strictly above that line (keeps conditions inside the same COBOL paragraph as
    the error line; avoids implicit ``IF`` without ``END-IF`` leaking into the next
    paragraph).
    """
    return [
        pred
        for pred, _branch in collect_enclosing_if_steps(
            lines,
            set_line_1based,
            max_depth=max_depth,
            max_upward_lines=max_upward_lines,
            min_if_line_1based=min_if_line_1based,
        )
    ]


def collect_enclosing_if_steps(
    lines: list[str],
    set_line_1based: int,
    *,
    max_depth: int = 16,
    max_upward_lines: int = 100,
    min_if_line_1based: int | None = None,
) -> list[tuple[str, str]]:
    """
    Like :func:`collect_enclosing_if_predicates`, but also reports which branch of
    each enclosing ``IF`` reaches the statement.

    Returns ``(predicate, branch)`` pairs from **innermost** to **outermost**,
    where ``branch`` is ``"then"`` (statement reached when the condition is TRUE)
    or ``"else"`` (reached via the ``ELSE`` branch).
    """
    idx = set_line_1based - 1
    if idx < 0 or idx >= len(lines):
        return []
    steps: list[tuple[str, str]] = []
    cur = idx
    while len(steps) < max_depth:
        if_line = find_preceding_if_line(lines, cur)
        if if_line is None:
            break
        if_line_1based = if_line + 1
        if min_if_line_1based is not None and if_line_1based < min_if_line_1based:
            break
        if set_line_1based - if_line_1based > max_upward_lines:
            break
        pred = extend_if_predicate(lines, if_line, cur)
        branch = if_branch_for_line(lines, if_line, idx)
        if pred:
            steps.append((pred, branch))
        cur = if_line
    return steps


def collect_evaluate_when_branch(lines: list[str], set_line_1based: int) -> list[str]:
    """
    If the statement sits under an ``EVALUATE``, collect ``WHEN`` predicates
    from the branch entry down to the statement (inner ``WHEN`` first).

    Best-effort: stops at the first ``EVALUATE`` going upward; nested
    ``END-EVALUATE`` blocks are not followed into.
    """
    idx = set_line_1based - 1
    if idx < 0:
        return []
    i = idx - 1
    whens: list[str] = []
    while i >= 0:
        s = lines[i].strip()
        u = s.upper()
        if u.startswith("END-EVALUATE"):
            return []
        if u.startswith("EVALUATE"):
            break
        if u.startswith("WHEN "):
            rest = s[5:].strip()
            whens.append(rest.rstrip("."))
        i -= 1
    else:
        return []
    return whens


def enrich_corora_occurrence_control_flow(
    occ: ErrorOccurrence,
    lines: list[str],
    *,
    max_upward_lines: int = 100,
    paragraph_start_line: int | None = None,
) -> None:
    """
    Fill ``occ.condition`` with data names used in enclosing IF / WHEN predicates,
    and ``occ.row_summary`` with a short nested-control-flow narrative.

    ``paragraph_start_line`` (1-based): only ``IF`` headers on or after this line
    are included in the chain (same paragraph as the error statement).
    """
    if_steps = collect_enclosing_if_steps(
        lines,
        occ.location.line,
        max_upward_lines=max_upward_lines,
        min_if_line_1based=paragraph_start_line,
    )
    if_chain = [pred for pred, _ in if_steps]
    when_chain = collect_evaluate_when_branch(lines, occ.location.line)

    idents_ordered: list[str] = []
    seen: set[str] = set()
    for pred in if_chain + when_chain:
        for name in identifiers_in_condition(pred):
            if name not in seen:
                seen.add(name)
                idents_ordered.append(name)
    occ.condition = ", ".join(idents_ordered)

    occ.related = [
        VariableRef(name=n, role="if_or_when_condition", line=None)
        for n in idents_ordered
    ]

    layers: list[str] = []
    for w in when_chain:
        p = w.strip()
        if p:
            layers.append(f"WHEN {p[:140]}{'...' if len(p) > 140 else ''}")
    for pred, branch in if_steps:
        p = pred.strip()
        if p:
            # Marker records the branch that reaches the error: [true] = error set
            # when the condition holds; [false] = error set via the IF's ELSE.
            marker = " [true]" if branch == "then" else " [false]"
            layers.append(f"IF {p[:140]}{'...' if len(p) > 140 else ''}{marker}")

    if layers:
        path = " -> ".join(layers)
        act = occ.setting_statement.strip()
        if len(act) > 130:
            act = act[:127] + "..."
        summary = f"Nested control path (inner to outer): {path}. {act}"
    else:
        summary = summarize_row_heuristic_fallback(occ)
    if len(summary) > 900:
        summary = summary[:897] + "..."
    occ.row_summary = summary


def summarize_row_heuristic_fallback(occ: ErrorOccurrence) -> str:
    """Minimal row text when no enclosing IF/WHEN was found."""
    if occ.error_message_literal.strip():
        return occ.error_message_literal.strip().replace("'", "").replace('"', "").title()
    return f"Error {occ.code}"


def collect_paths_for_line(
    paragraph_lines: list[str],
    line_idx_in_para: int,
) -> str:
    """
    Very small slice of 'path' logic: walk backward for IF/EVALUATE/WHEN headers.
    """
    buf: deque[str] = deque(maxlen=20)
    j = line_idx_in_para
    if not paragraph_lines or j < 0 or j >= len(paragraph_lines):
        return ""
    while j >= 0 and len(buf) < 20:
        ln = paragraph_lines[j].strip()
        u = ln.upper()
        if u.startswith("IF ") or u.startswith("ELSE") or u.startswith("WHEN "):
            buf.appendleft(ln)
        j -= 1
    return "\n".join(buf) if buf else ""
