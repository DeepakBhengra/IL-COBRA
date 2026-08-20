"""Build decision flowcharts from ``row_summary`` (and optional ``condition``).

Outputs **Mermaid** ``flowchart TD`` text (no extra dependencies) and optional
**Graphviz DOT** for rendering with the ``dot`` tool.

``row_summary`` values produced by CORORA enrichment look like::

    Nested control path (inner to outer): IF A -> IF B. MOVE ...

Those layers are **innermost-first**; this module reverses them so the chart
reads top-down as control flows from outer tests toward the error path.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


NESTED_PREFIX = "Nested control path (inner to outer):"

_STEP_SPLIT = re.compile(r"\s*->\s*")

# Mermaid node ids: letter + digits only is safest.
_ID_RE = re.compile(r"[^A-Za-z0-9]+")


@dataclass
class DecisionStep:
    """One IF or WHEN along the path to the error."""

    kind: Literal["IF", "WHEN"]
    predicate: str
    #: For IF steps: "then" if the error path is taken when the condition is TRUE,
    #: "else" if via the ELSE branch, "" if unknown (legacy summaries).
    branch: str = ""


@dataclass
class ParsedSummary:
    """Structured view of a row summary for diagramming."""

    steps: list[DecisionStep] = field(default_factory=list)
    action: str = ""
    raw_summary: str = ""
    fallback_condition: str = ""


def _sanitize_label(s: str, *, max_len: int = 120) -> str:
    t = " ".join((s or "").split())
    t = t.replace('"', "'")
    if len(t) > max_len:
        t = t[: max_len - 1] + "…"
    return t or " "


def _mermaid_safe_inner_text(s: str, *, max_len: int = 120) -> str:
    """
    Text safe inside Mermaid ``["…"]`` and ``{"…"}`` node labels.

    COBOL predicates often contain ``( ) [ ] #`` etc.; unquoted ``()`` inside
    the ``{{…}}`` subroutine shape breaks the parser — we use quoted rhombus
    ``id{"…"}`` instead and normalize characters that still break quoted strings.
    """
    t = _sanitize_label(s, max_len=max_len)
    t = (
        t.replace("\\", "/")
        .replace("#", "＃")
        .replace("[", "［")
        .replace("]", "］")
        .replace("`", "'")
        .replace("{", "｛")
        .replace("}", "｝")
        .replace("<", "〈")
        .replace(">", "〉")
    )
    t = t.replace('"', "'")
    return t or " "


def _next_node_id(prefix: str, used: dict[str, int]) -> str:
    key = _ID_RE.sub("", prefix)[:16] or "N"
    n = used.get(key, 0)
    used[key] = n + 1
    return f"{key}{n}"


def parse_row_summary(text: str) -> ParsedSummary:
    """
    Parse ``row_summary`` text into decision steps.

    Handles CORORA-style nested paths; otherwise returns empty ``steps`` so the
    caller can fall back to ``condition``.
    """
    raw = (text or "").strip()
    out = ParsedSummary(raw_summary=raw)

    idx = raw.upper().find(NESTED_PREFIX.upper())
    if idx < 0:
        return out

    rest = raw[idx + len(NESTED_PREFIX) :].strip()
    path_part = rest
    action = ""

    # Tail after ". " is usually the setting statement (MOVE / SET …).
    low = rest.lower()
    if ". move " in low or ". set " in low or ". compute " in low:
        cut = max(low.rfind(". move "), low.rfind(". set "), low.rfind(". compute "))
        if cut >= 0:
            path_part = rest[:cut].strip()
            action = rest[cut + 2 :].strip()

    for segment in _STEP_SPLIT.split(path_part):
        seg = segment.strip()
        if not seg:
            continue
        u = seg.upper()
        if u.startswith("WHEN "):
            pred = seg[5:].strip()
            out.steps.append(DecisionStep(kind="WHEN", predicate=pred))
        elif u.startswith("IF "):
            pred = seg[3:].strip()
            branch = ""
            bm = re.search(r"\s*\[(true|false)\]\s*$", pred, re.IGNORECASE)
            if bm:
                branch = "then" if bm.group(1).lower() == "true" else "else"
                pred = pred[: bm.start()].strip()
            out.steps.append(DecisionStep(kind="IF", predicate=pred, branch=branch))
        else:
            # Unknown segment; keep as IF-shaped label for visibility.
            out.steps.append(DecisionStep(kind="IF", predicate=seg))

    out.action = action
    return out


def parse_jsonl_row(row: dict) -> ParsedSummary:
    """Combine ``row_summary`` and optional ``condition`` from a manifest JSONL row."""
    ps = parse_row_summary(str(row.get("row_summary") or ""))
    cond = str(row.get("condition") or "").strip()
    if cond:
        ps.fallback_condition = cond
    if not ps.action:
        stmt = str(row.get("statement") or "").strip()
        if stmt:
            ps.action = stmt
    return ps


def build_mermaid(
    parsed: ParsedSummary,
    *,
    outcome_title: str = "Error handling",
    false_label: str = "False",
    true_label: str = "True",
    when_match_label: str = "Match",
    when_else_label: str = "No match",
) -> str:
    """
    Return a Mermaid ``flowchart TD`` document.

    Layers from nested summaries are drawn **outer → inner** (reverse of
    inner-to-outer storage). A simple ``condition`` fallback yields one
    decision diamond.

    For **IF** nodes, the branch that reaches the error (``DecisionStep.branch``)
    continues toward the error path and the opposite branch goes to "No error on
    this branch"; when the branch is unknown, **False** continues (legacy default).
    **WHEN** nodes use Match / No match.
    """
    lines: list[str] = ["flowchart TD"]
    used_ids: dict[str, int] = {}

    start_id = _next_node_id("Start", used_ids)
    ot = _mermaid_safe_inner_text(outcome_title)
    lines.append(f'    {start_id}(["{ot}"])')

    steps = list(parsed.steps)
    steps.reverse()

    if not steps and parsed.fallback_condition:
        steps = [DecisionStep(kind="IF", predicate=parsed.fallback_condition)]

    if not steps:
        leaf_id = _next_node_id("Outcome", used_ids)
        lbl = _mermaid_safe_inner_text(parsed.raw_summary or "No branching parsed")
        lines.append(f'    {leaf_id}["{lbl}"]')
        lines.append(f"    {start_id} --> {leaf_id}")
        return "\n".join(lines) + "\n"

    # Create the decision diamonds (outer -> inner) up front so each diamond can
    # label its OWN two outgoing edges (error path vs. no-error path).
    diamonds: list[tuple[str, DecisionStep]] = []
    for st in steps:
        node_id = _next_node_id(st.kind, used_ids)
        # Quoted rhombus id{"…"}: COBOL ``( )`` in predicates breaks ``{{…}}`` subroutine grammar.
        label = _mermaid_safe_inner_text(f"{st.kind} {st.predicate}")
        lines.append(f'    {node_id}{{"{label}"}}')
        diamonds.append((node_id, st))

    end_id = _next_node_id("Set", used_ids)
    act = parsed.action or parsed.raw_summary or "Set error / continue path"
    lines.append(f'    {end_id}["{_mermaid_safe_inner_text(act)}"]')

    lines.append(f"    {start_id} --> {diamonds[0][0]}")

    for i, (node_id, st) in enumerate(diamonds):
        nxt = diamonds[i + 1][0] if i + 1 < len(diamonds) else end_id
        if st.kind == "WHEN":
            lines.append(
                f'    {node_id} -->|"{_mermaid_safe_inner_text(when_match_label, max_len=40)}"| {nxt}'
            )
            alt_id = _next_node_id("Else", used_ids)
            wel = _mermaid_safe_inner_text(when_else_label, max_len=80)
            lines.append(f'    {alt_id}(["{wel}"])')
            lines.append(
                f'    {node_id} -->|"{_mermaid_safe_inner_text(when_else_label, max_len=40)}"| {alt_id}'
            )
        else:
            # The branch that reaches the error continues toward it; the other
            # branch exits with no error. Unknown branch defaults to False (legacy).
            err_label, skip_label = (
                (true_label, false_label)
                if st.branch == "then"
                else (false_label, true_label)
            )
            lines.append(
                f'    {node_id} -->|"{_mermaid_safe_inner_text(err_label, max_len=40)}"| {nxt}'
            )
            skip_id = _next_node_id("Skip", used_ids)
            skip_txt = _mermaid_safe_inner_text("No error on this branch", max_len=80)
            lines.append(f'    {skip_id}(["{skip_txt}"])')
            lines.append(
                f'    {node_id} -->|"{_mermaid_safe_inner_text(skip_label, max_len=40)}"| {skip_id}'
            )

    return "\n".join(lines) + "\n"


def build_dot(
    parsed: ParsedSummary,
    *,
    outcome_title: str = "Error handling",
    false_label: str = "False",
    true_label: str = "True",
    when_match_label: str = "Match",
    when_else_label: str = "No match",
) -> str:
    """Graphviz DOT directed graph (render with ``dot -Tpng file.dot -o out.png``)."""
    lines = [
        "digraph G {",
        '  graph [rankdir=TB];',
        '  node [fontname="Helvetica"];',
        '  edge [fontname="Helvetica"];',
    ]
    used_ids: dict[str, int] = {}

    start_id = _next_node_id("Start", used_ids)
    lines.append(f'  {start_id} [shape=plaintext, label="{_sanitize_label(outcome_title)}"];')

    steps = list(parsed.steps)
    steps.reverse()
    if not steps and parsed.fallback_condition:
        steps = [DecisionStep(kind="IF", predicate=parsed.fallback_condition)]

    if not steps:
        leaf_id = _next_node_id("Outcome", used_ids)
        lbl = _sanitize_label(parsed.raw_summary or "No branching parsed")
        lines.append(f'  {leaf_id} [shape=box, label="{lbl}"];')
        lines.append(f"  {start_id} -> {leaf_id};")
        lines.append("}")
        return "\n".join(lines) + "\n"

    diamonds: list[tuple[str, DecisionStep]] = []
    for st in steps:
        nid = _next_node_id(st.kind, used_ids)
        lbl = _sanitize_label(f"{st.kind} {st.predicate}")
        lines.append(f'  {nid} [shape=diamond, label="{lbl}"];')
        diamonds.append((nid, st))

    end_id = _next_node_id("Set", used_ids)
    act = parsed.action or parsed.raw_summary or "Set error"
    lines.append(f'  {end_id} [shape=box, label="{_sanitize_label(act)}"];')

    lines.append(f"  {start_id} -> {diamonds[0][0]};")

    for i, (nid, st) in enumerate(diamonds):
        nxt = diamonds[i + 1][0] if i + 1 < len(diamonds) else end_id
        if st.kind == "WHEN":
            alt_id = _next_node_id("Else", used_ids)
            lines.append(f'  {alt_id} [shape=box, label="{_sanitize_label(when_else_label)}"];')
            lines.append(f'  {nid} -> {nxt} [label="{_sanitize_label(when_match_label)}"];')
            lines.append(f'  {nid} -> {alt_id} [label="{_sanitize_label(when_else_label)}"];')
        else:
            skip_id = _next_node_id("Skip", used_ids)
            err_label, skip_label = (
                (true_label, false_label)
                if st.branch == "then"
                else (false_label, true_label)
            )
            lines.append(f'  {skip_id} [shape=box, label="{_sanitize_label("No error on this branch")}"];')
            lines.append(f'  {nid} -> {nxt} [label="{_sanitize_label(err_label)}"];')
            lines.append(f'  {nid} -> {skip_id} [label="{_sanitize_label(skip_label)}"];')

    lines.append("}")
    return "\n".join(lines) + "\n"


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def emit_flowcharts_from_jsonl(
    jsonl_path: Path,
    out_dir: Path,
    *,
    dot: bool = False,
) -> list[Path]:
    """
    For each row in ``errors.jsonl``, write ``flow_<index>.mmd`` (and optional ``.dot``).

    Filenames are stable by row order (1-based index).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for i, row in enumerate(_iter_jsonl(jsonl_path), start=1):
        parsed = parse_jsonl_row(row)
        title_bits = [
            str(row.get("program") or ""),
            str(row.get("error_code") or ""),
            str(row.get("line") or ""),
        ]
        title = " — ".join(b for b in title_bits if b)
        mmd = build_mermaid(parsed, outcome_title=title or "Flow")
        base = out_dir / f"flow_{i:04d}"
        mmd_path = base.with_suffix(".mmd")
        mmd_path.write_text(mmd, encoding="utf-8")
        written.append(mmd_path)
        if dot:
            dp = base.with_suffix(".dot")
            dp.write_text(build_dot(parsed, outcome_title=title or "Flow"), encoding="utf-8")
            written.append(dp)
    return written


def _cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Generate Mermaid (and optional DOT) flowcharts from row_summary / errors.jsonl."
    )
    p.add_argument(
        "input",
        nargs="?",
        help="Path to errors.jsonl, or omit with --text for inline summary",
    )
    p.add_argument(
        "--text",
        "-t",
        help="Raw row_summary text (skips JSONL)",
    )
    p.add_argument(
        "--condition",
        "-c",
        help="Optional COBOL condition when summary has no nested path",
    )
    p.add_argument(
        "--out",
        "-o",
        type=Path,
        default=Path("out/flowcharts"),
        help="Output file (.mmd) or directory for JSONL batch mode",
    )
    p.add_argument("--dot", action="store_true", help="Also write Graphviz DOT")
    p.add_argument(
        "--batch",
        action="store_true",
        help="Treat input as JSONL and write flow_*.mmd into --out directory",
    )
    args = p.parse_args(argv)

    if args.text is not None:
        ps = parse_row_summary(args.text)
        if args.condition:
            ps.fallback_condition = args.condition.strip()
        mmd = build_mermaid(ps)
        out: Path = args.out
        if out.suffix.lower() != ".mmd":
            out = out / "inline_flow.mmd"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(mmd, encoding="utf-8")
        if args.dot:
            dout = out.with_suffix(".dot")
            dout.write_text(build_dot(ps), encoding="utf-8")
        return 0

    if not args.input:
        p.error("Provide errors.jsonl path or use --text")

    inp = Path(args.input)
    if args.batch or inp.name.endswith(".jsonl"):
        written = emit_flowcharts_from_jsonl(inp, args.out, dot=args.dot)
        if not written:
            print(f"No rows written from {inp}")
            return 1
        print(f"Wrote {len(written)} file(s) under {args.out.resolve()}")
        return 0

    ps = parse_jsonl_row(json.loads(inp.read_text(encoding="utf-8")))
    # Single JSON object file
    mmd = build_mermaid(ps)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(mmd, encoding="utf-8")
    if args.dot:
        args.out.with_suffix(".dot").write_text(build_dot(ps), encoding="utf-8")
    return 0


def main() -> None:
    raise SystemExit(_cli())


if __name__ == "__main__":
    main()
