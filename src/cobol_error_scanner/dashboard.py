"""Streamlit dashboard for COBOL error-code scan results."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from cobol_error_scanner.mapping_catalog import (
    MAX_ERROR_FIELD_INPUT_LEN,
    resolve_mapping_directory,
)
from cobol_error_scanner.mapping_resolve import apply_mapping_filter_fallback, resolve_mapped_error_field
from cobol_error_scanner.docgen import build_manifest, write_jsonl, write_manifest_json, write_markdown_table
from cobol_error_scanner.flowchart_from_summary import build_mermaid, parse_jsonl_row
from cobol_error_scanner.pipeline import filter_programs_by_error_code, scan_root
from cobol_error_scanner.summarizer import SummarizerConfig


DEFAULT_SOURCE_ROOT = Path("samples")
DEFAULT_RULES_PATH = Path("config/error_rules.json")
DEFAULT_OUT_DIR = Path("out")
DEFAULT_CORORA_MAPPINGS = Path("error_mapping_files")

TABLE_COLUMNS = [
    "error_code",
    "error_field",
    "program",
    "line",
    "paragraph",
    "section",
    "condition",
    "parameters",
    "error_message",
    "row_summary",
    "mapping_detail",
]

DETAIL_FIELDS = [
    ("Program", "program"),
    ("Error code", "error_code"),
    ("Error Field", "error_field"),
    ("File", "file"),
    ("Line", "line"),
    ("Paragraph", "paragraph"),
    ("Section", "section"),
    ("Condition", "condition"),
    ("Parameters", "parameters"),
    ("Error message", "error_message"),
    ("Statement", "statement"),
    ("Summary", "row_summary"),
    ("Mapping detail", "mapping_detail"),
]

_MOVE_TO_TARGET = re.compile(r"\bMOVE\s+.+?\s+TO\s+([\w-]+)", re.IGNORECASE)
_SET_TO_TARGET = re.compile(r"\bSET\s+([\w-]+)\s+TO\s+\S+", re.IGNORECASE)


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _extract_error_field(statement: str) -> str:
    """Return the COBOL field or condition name that receives the error mapping."""
    text = statement.strip()
    if not text:
        return ""
    for pattern in (_MOVE_TO_TARGET, _SET_TO_TARGET):
        match = pattern.search(text)
        if match:
            return match.group(1)
    return ""


@st.cache_data(show_spinner=False)
def load_records(jsonl_path: str) -> list[dict[str, Any]]:
    path = Path(jsonl_path)
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


@st.cache_data(show_spinner=False)
def load_manifest(manifest_path: str) -> dict[str, Any]:
    path = Path(manifest_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def records_to_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    for column in set(
        TABLE_COLUMNS + ["file", "statement", "logic_context", "related", "summary", "search_text", "mapping_detail"]
    ):
        if column not in frame.columns:
            frame[column] = ""
    frame["error_field"] = frame.apply(
        lambda row: row["error_field"] or _extract_error_field(str(row.get("statement", ""))),
        axis=1,
    )
    if "line" in frame.columns:
        def _normalize_line_cell(v: Any) -> Any:
            if v == "" or v is None:
                return ""
            if isinstance(v, float) and pd.isna(v):
                return ""
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return v

        frame["line"] = frame["line"].map(_normalize_line_cell)
    return frame


def _optional_path(raw: str) -> Path | None:
    raw = raw.strip()
    return Path(raw) if raw else None


def apply_filters(frame: pd.DataFrame) -> pd.DataFrame:
    filtered = frame.copy()

    programs = sorted(value for value in filtered["program"].dropna().astype(str).unique() if value)
    selected_programs = st.sidebar.multiselect("Programs", programs)
    if selected_programs:
        filtered = filtered[filtered["program"].isin(selected_programs)]

    error_code_input = st.sidebar.text_input(
        "Error codes",
        placeholder="e.g. E1 or E1, X2",
        help="Type one or more 2-character error codes separated by commas or spaces. Case-insensitive.",
        max_chars=64,
    )
    raw_tokens = [token.strip() for token in error_code_input.replace(",", " ").split() if token.strip()]
    invalid_tokens = [token for token in raw_tokens if len(token) != 2]
    if invalid_tokens:
        st.sidebar.error(
            "Error codes must be exactly 2 characters. Invalid: "
            + ", ".join(f"'{token}'" for token in invalid_tokens)
        )
    else:
        typed_codes = [token.upper() for token in raw_tokens]
        if typed_codes:
            filtered = filtered[filtered["error_code"].astype(str).str.upper().isin(typed_codes)]

    query = st.sidebar.text_input("Search", placeholder="condition, parameter, message, paragraph...")
    if query.strip():
        haystack = (
            filtered["search_text"].fillna("").astype(str)
            + " "
            + filtered["error_field"].fillna("").astype(str)
        ).str.lower()
        filtered = filtered[haystack.str.contains(query.strip().lower(), regex=False)]

    field_contains = st.sidebar.text_input(
        "Error field contains",
        placeholder="substring of CORORA-R-… / CORORL-R-… name",
        help="Filter loaded rows where the Error Field column contains this text (case-insensitive). Max 30 characters.",
        max_chars=MAX_ERROR_FIELD_INPUT_LEN,
    )
    if field_contains.strip():
        fc = field_contains.strip().lower()
        col = filtered["error_field"].fillna("").astype(str).str.lower()
        filtered = filtered[col.str.contains(fc, regex=False)]

    return filtered


def run_scan(
    source_root: Path,
    rules_path: Path,
    out_dir: Path,
    summarizer: str,
    *,
    error_code: str = "",
    error_field: str = "",
    corora_mappings: Path | None = None,
) -> tuple[int, int, str]:
    ef = error_field.strip()[:MAX_ERROR_FIELD_INPUT_LEN]
    if ef:
        config = SummarizerConfig(provider=summarizer if summarizer in {"heuristic", "openai"} else "heuristic")
        programs = resolve_mapped_error_field(
            source_root,
            ef,
            mapping_dir_explicit=corora_mappings,
            summarizer=config,
        )
        table_name = "error_field_table.md"
        manifest = build_manifest(source_root, programs)
        write_jsonl(manifest, out_dir / "errors.jsonl")
        write_manifest_json(manifest, out_dir / "manifest.json")
        write_markdown_table(manifest, out_dir / table_name)
        finding_count = sum(len(program.occurrences) for program in programs)
        return len(programs), finding_count, table_name

    requested_code = error_code.strip().upper()
    if requested_code and len(requested_code) != 2:
        raise ValueError(f"Focused error-code scans require exactly 2 characters: {requested_code!r}")

    config = SummarizerConfig(provider=summarizer if summarizer in {"heuristic", "openai"} else "heuristic")
    programs = scan_root(source_root, rules_path, summarizer=config)
    table_name = "errors_table.md"

    if requested_code:
        standard_matches = filter_programs_by_error_code(programs, requested_code, summarizer=config)
        mapping_dir = resolve_mapping_directory(source_root, corora_mappings)
        corora_matches = []
        if mapping_dir is not None:
            corora_matches = apply_mapping_filter_fallback(
                source_root,
                requested_code,
                mapping_dir=corora_mappings,
                summarizer=config,
            )
        programs = corora_matches if corora_matches else standard_matches
        table_name = "error_table.md"

    manifest = build_manifest(source_root, programs)
    write_jsonl(manifest, out_dir / "errors.jsonl")
    write_manifest_json(manifest, out_dir / "manifest.json")
    write_markdown_table(manifest, out_dir / table_name)
    finding_count = sum(len(program.occurrences) for program in programs)
    return len(programs), finding_count, table_name


def render_scan_controls() -> tuple[Path, Path, Path]:
    st.sidebar.header("Scan Input")
    source_root = Path(st.sidebar.text_input("COBOL source root", str(DEFAULT_SOURCE_ROOT)))
    rules_path = Path(st.sidebar.text_input("Rules file", str(DEFAULT_RULES_PATH)))
    out_dir = Path(st.sidebar.text_input("Output folder", str(DEFAULT_OUT_DIR)))
    error_code_raw = st.sidebar.text_input(
        "Focused error code",
        placeholder="optional, e.g. 1C",
        help="Optional. Run a focused scan for exactly one 2-character code, including CORORA/CORORL mapping fallback.",
        max_chars=8,
    )
    error_code = error_code_raw.strip()
    error_field_raw = st.sidebar.text_input(
        "Focused Error Field",
        placeholder="e.g. ERR-NO-SEC-EDD-OVRD",
        help=(
            "Optional. Max 30 characters. Substring search in CORORA and CORORL one- and two-char "
            "mapping files (maps ERR-… to CORORA-R-ERR-… / CORORL-R-ERR-…). If set, overrides "
            "focused error code for this run."
        ),
        max_chars=MAX_ERROR_FIELD_INPUT_LEN,
    )
    error_field = error_field_raw.strip()[:MAX_ERROR_FIELD_INPUT_LEN]
    focused_error: str | None = None
    if error_field:
        focused_error = None
        if error_code:
            st.sidebar.caption("Using **Focused Error Field**; focused error code is ignored for this run.")
    elif error_code and len(error_code) != 2:
        focused_error = (
            f"Focused error code must be exactly 2 characters. "
            f"You entered '{error_code}' ({len(error_code)} character(s))."
        )
        st.sidebar.error(focused_error)

    corora_mappings = _optional_path(
        st.sidebar.text_input(
            "Mapping folder",
            str(DEFAULT_CORORA_MAPPINGS),
            help=(
                "Folder containing CORORA_* and CORORL_* mapping fragments "
                "(e.g. CORORA_TWO_CHAR_ERROR, CORORL_TWO_CHAR_ERROR). Leave blank to auto-detect."
            ),
        )
    )
    summarizer = st.sidebar.selectbox("Summarizer", ["heuristic", "openai"])

    if st.sidebar.button("Run scan", type="primary", disabled=focused_error is not None):
        if focused_error is not None:
            st.sidebar.error(focused_error)
        else:
            try:
                st.session_state["scan_results_ready"] = False
                with st.spinner("Scanning COBOL sources..."):
                    program_count, finding_count, table_name = run_scan(
                        source_root,
                        rules_path,
                        out_dir,
                        summarizer,
                        error_code=error_code,
                        error_field=error_field,
                        corora_mappings=corora_mappings,
                    )
                st.cache_data.clear()
                st.session_state["scan_results_ready"] = True
                st.sidebar.success(
                    f"Scanned {program_count} program(s), found {finding_count} finding(s). Wrote {table_name}."
                )
            except Exception as exc:
                st.session_state["scan_results_ready"] = False
                st.sidebar.error(f"Scan failed: {exc}")

    return source_root, rules_path, out_dir


def render_metrics(frame: pd.DataFrame) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Findings", len(frame))
    col2.metric("Programs", frame["program"].nunique())
    col3.metric("Error codes", frame["error_code"].nunique())
    col4.metric("Source files", frame["file"].nunique())


def render_table(filtered: pd.DataFrame) -> None:
    table = filtered[TABLE_COLUMNS].copy()
    for column in table.columns:
        if table[column].dtype == object:
            table[column] = table[column].map(_format_value)
    table = table.rename(columns={"error_field": "Error Field"})
    table.insert(0, "S.No", range(1, len(table) + 1))

    table_html = table.to_html(index=False, escape=True, classes="mf-findings-table")
    st.markdown(
        f'<div class="mf-table-wrap">{table_html}</div>',
        unsafe_allow_html=True,
    )

    csv_table = filtered[TABLE_COLUMNS + ["file", "statement", "logic_context"]].rename(
        columns={"error_field": "Error Field"}
    )
    csv_table.insert(0, "S.No", range(1, len(csv_table) + 1))
    csv_data = csv_table.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download filtered CSV",
        csv_data,
        file_name="cobol_error_findings.csv",
        mime="text/csv",
    )


def _mermaid_embed_html(chart: str, graph_id: str) -> str:
    """Single-page HTML that renders ``chart`` with Mermaid (CDN) for ``components.html``."""
    spec = json.dumps(chart)
    gid = json.dumps(graph_id)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  html, body {{
    margin: 0;
    height: 100%;
    background: #000;
    color: #33ff33;
    font-family: "IBM Plex Mono", Consolas, monospace;
    overflow: hidden;
  }}
  /* Non-scrolling frame: HUD is positioned here so it stays bottom-right while #viewport scrolls. */
  #chartShell {{
    position: relative;
    width: 100%;
    height: 100%;
    min-height: 100%;
    box-sizing: border-box;
    overflow: hidden;
    background: #000;
  }}
  #viewport {{
    position: absolute;
    inset: 0;
    box-sizing: border-box;
    overflow: auto;
    background: #000;
  }}
  #zoomRoot {{
    display: inline-block;
    transform-origin: 0 0;
    padding: 0.5rem;
  }}
  #zoomRoot svg {{ display: block; max-width: none; height: auto; }}
  #status {{ padding: 0.5rem; opacity: 0.7; }}
  #zoomHud {{
    position: absolute;
    bottom: 10px;
    right: 10px;
    z-index: 100;
    display: none;
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
    padding: 8px 10px;
    min-width: 7.5rem;
    background: rgba(10, 10, 10, 0.94);
    border: 1px solid #00cc33;
    border-radius: 2px;
    box-shadow: 0 2px 14px rgba(0, 0, 0, 0.65);
    pointer-events: auto;
  }}
  #zoomHud.visible {{ display: flex; }}
  .zoomHud-btns {{
    display: flex;
    flex-direction: row;
    justify-content: stretch;
    gap: 5px;
  }}
  #zoomHud button {{
    flex: 1;
    background: #000;
    color: #ffb000;
    border: 1px solid #00cc33;
    font-family: inherit;
    font-size: 1rem;
    font-weight: 700;
    line-height: 1;
    padding: 0.4rem 0.35rem;
    cursor: pointer;
    text-transform: none;
  }}
  #zoomHud button:hover {{ background: #061a06; color: #ffd479; }}
  #zoomHud #zreset {{ font-size: 0.72rem; font-weight: 600; letter-spacing: 0.02em; }}
  #zlabel {{
    color: #33ff33;
    font-size: 0.75rem;
    text-align: center;
    border-top: 1px solid #0d330d;
    padding-top: 4px;
    margin-top: 2px;
  }}
  .zoomHud-hint {{
    color: #1faa1f;
    font-size: 0.62rem;
    text-align: center;
    line-height: 1.25;
    opacity: 0.95;
  }}
</style></head>
<body>
<div id="chartShell">
  <div id="viewport">
    <div id="status">Rendering diagram…</div>
    <div id="zoomRoot" style="display:none"></div>
  </div>
  <div id="zoomHud" aria-label="Diagram zoom">
    <div class="zoomHud-btns">
      <button type="button" id="zin" title="Zoom in">+</button>
      <button type="button" id="zout" title="Zoom out">−</button>
      <button type="button" id="zreset" title="Reset to 100%">1:1</button>
    </div>
    <div id="zlabel">100%</div>
    <div class="zoomHud-hint">Ctrl + wheel to zoom</div>
  </div>
</div>
<script type="module">
const spec = {spec};
const graphId = {gid};
const chartShell = document.getElementById("chartShell");
const zoomHud = document.getElementById("zoomHud");
const viewport = document.getElementById("viewport");
const zoomRoot = document.getElementById("zoomRoot");
const statusEl = document.getElementById("status");
const zin = document.getElementById("zin");
const zout = document.getElementById("zout");
const zreset = document.getElementById("zreset");
const zlabel = document.getElementById("zlabel");

let scale = 1;
const MIN = 0.25;
const MAX = 3.5;
const STEP = 0.2;

function clamp(v, a, b) {{ return Math.max(a, Math.min(b, v)); }}

function applyScale() {{
  scale = clamp(scale, MIN, MAX);
  zoomRoot.style.transform = "scale(" + scale + ")";
  zlabel.textContent = Math.round(scale * 100) + "%";
}}

zin.addEventListener("click", () => {{ scale += STEP; applyScale(); }});
zout.addEventListener("click", () => {{ scale -= STEP; applyScale(); }});
zreset.addEventListener("click", () => {{ scale = 1; applyScale(); }});

/* Wheel zoom anywhere over the chart shell (diagram or HUD) without scrolling the parent page. */
chartShell.addEventListener("wheel", (e) => {{
  if (!e.ctrlKey) return;
  e.preventDefault();
  const delta = e.deltaY > 0 ? -0.12 : 0.12;
  scale += delta;
  applyScale();
}}, {{ passive: false }});

try {{
  const mermaid = (await import("https://cdn.jsdelivr.net/npm/mermaid@10.9.0/dist/mermaid.esm.min.mjs")).default;
  await mermaid.initialize({{
    startOnLoad: false,
    securityLevel: "loose",
    theme: "dark",
    flowchart: {{ useMaxWidth: true, htmlLabels: true, curve: "basis" }},
    themeVariables: {{
      fontFamily: "IBM Plex Mono, Consolas, monospace",
      primaryColor: "#0a0a0a",
      primaryTextColor: "#33ff33",
      secondaryColor: "#001a00",
      tertiaryColor: "#0a0a0a",
      lineColor: "#00cc33",
      mainBkg: "#000000",
      textColor: "#33ff33",
      nodeBorder: "#00cc33",
      clusterBkg: "#0a0a0a",
      titleColor: "#ffb000",
      edgeLabelBackground: "#0a0a0a",
    }},
  }});
  const {{ svg }} = await mermaid.render(graphId, spec);
  statusEl.style.display = "none";
  zoomRoot.style.display = "inline-block";
  zoomRoot.innerHTML = svg;
  scale = 1;
  applyScale();
  zoomHud.classList.add("visible");
}} catch (e) {{
  statusEl.textContent = "Could not load Mermaid from CDN: " + (e && e.message ? e.message : e);
}}
</script>
</body></html>"""


def _flowchart_row_label(filtered: pd.DataFrame, position: int) -> str:
    """Label for selectbox: S.No + code + program + line (matches findings table order)."""
    row = filtered.iloc[position]
    sn = position + 1
    code = _format_value(row.get("error_code", ""))
    prog = _format_value(row.get("program", ""))
    ln = _format_value(row.get("line", ""))
    return f"Finding {sn}: {code} | {prog} | line {ln}"


def render_finding_flowchart_section(filtered: pd.DataFrame) -> None:
    """Control-flow diagram for any filtered finding (same order as the table / S.No)."""
    if filtered.empty:
        return
    st.subheader("Control flow chart")
    n = len(filtered)
    positions = list(range(n))
    pick = st.selectbox(
        "Finding for diagram",
        options=positions,
        index=0,
        format_func=lambda i: _flowchart_row_label(filtered, int(i)),
        key="flowchart_finding_pick",
        help="Choose which row from the filtered findings table to diagram (after error-code and other filters).",
    )
    pos = int(pick)
    row = filtered.iloc[pos]
    rec = {k: ("" if (isinstance(v, float) and pd.isna(v)) else v) for k, v in row.to_dict().items()}
    parsed = parse_jsonl_row(rec)
    title_bits = [
        str(rec.get("program") or ""),
        str(rec.get("error_code") or ""),
        str(rec.get("line") or ""),
    ]
    title = " — ".join(b for b in title_bits if b) or f"Finding {pos + 1}"
    chart = build_mermaid(parsed, outcome_title=title)
    st.caption(
        "Derived from **Summary** (`row_summary`) and **Condition** for the selected row "
        f"(S.No **{pos + 1}** of **{n}** in the current table)."
    )
    with st.expander("View Mermaid source", expanded=False):
        st.code(chart, language="text")
    graph_id = f"mfFlow{pos}_{abs(hash(chart)) % 1_000_000_000}"
    components.html(
        _mermaid_embed_html(chart, graph_id),
        height=560,
        scrolling=True,
    )


def render_finding_details(filtered: pd.DataFrame, manifest: dict[str, Any]) -> None:
    st.subheader("Finding Details")
    if filtered.empty:
        st.info("No findings match the current filters.")
        return

    options = list(filtered.index)
    selected = st.selectbox(
        "Select a finding",
        options,
        format_func=lambda idx: (
            f"{filtered.at[idx, 'error_code']} | {filtered.at[idx, 'program']} | line {filtered.at[idx, 'line']}"
        ),
    )
    row = filtered.loc[selected]

    for label, key in DETAIL_FIELDS:
        value = _format_value(row.get(key, ""))
        if value:
            st.markdown(f"**{label}:** {value}")

    program_summaries = {
        program.get("program_id"): program.get("plain_english", "")
        for program in manifest.get("programs", [])
        if isinstance(program, dict)
    }
    program_summary = program_summaries.get(row.get("program"))
    if program_summary:
        st.markdown("**Program summary:**")
        st.write(program_summary)

    related = row.get("related")
    if isinstance(related, list) and related:
        st.markdown("**Related variables:**")
        st.json(related)

    logic_context = _format_value(row.get("logic_context", ""))
    if logic_context:
        st.markdown("**Logic context:**")
        st.code(logic_context, language="cobol")


_MAINFRAME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=VT323&family=IBM+Plex+Mono:wght@400;600&display=swap');

:root {
    --mf-bg:        #000000;
    --mf-surface:   #0a0a0a;
    --mf-border:    #00CC33;
    --mf-green:     #33FF33;
    --mf-green-dim: #1FAA1F;
    --mf-amber:     #FFB000;
    --mf-amber-hi:  #FFD479;
    --mf-mono:      'IBM Plex Mono', 'VT323', 'Courier New', Consolas, monospace;
}

html, body, .stApp, [data-testid="stAppViewContainer"],
[data-testid="stHeader"], [data-testid="stSidebar"] {
    background-color: var(--mf-bg) !important;
    color: var(--mf-green) !important;
    font-family: var(--mf-mono) !important;
}

[data-testid="stHeader"] { box-shadow: 0 1px 0 var(--mf-border) inset; }

.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3, [data-testid="stSidebar"] h4 {
    color: var(--mf-amber) !important;
    font-family: var(--mf-mono) !important;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-bottom: 1px solid var(--mf-border);
    padding-bottom: 0.25rem;
}

.stApp h1 {
    font-size: clamp(1.25rem, 2.4vw, 2rem) !important;
    line-height: 1.15 !important;
    letter-spacing: 0.02em !important;
    white-space: nowrap !important;
    overflow: hidden;
    text-overflow: ellipsis;
}

.stApp p, .stApp span, .stApp label, .stApp li, .stApp code,
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label {
    color: var(--mf-green) !important;
    font-family: var(--mf-mono) !important;
}

.stApp [data-testid="stCaptionContainer"],
.stApp small, .stApp .stCaption {
    color: var(--mf-green-dim) !important;
    font-family: var(--mf-mono) !important;
}

.stApp strong, .stApp b { color: var(--mf-amber-hi) !important; }

.stApp input, .stApp textarea, .stApp select,
[data-baseweb="input"] input, [data-baseweb="select"] div, [data-baseweb="textarea"] textarea {
    background-color: var(--mf-surface) !important;
    color: var(--mf-green) !important;
    border: 1px solid var(--mf-border) !important;
    font-family: var(--mf-mono) !important;
    caret-color: var(--mf-amber) !important;
}

.stApp [data-baseweb="input"] input,
.stApp [data-baseweb="textarea"] textarea {
    color: #FF4040 !important;
    caret-color: #FF4040 !important;
}

.stApp [data-baseweb="input"] input::placeholder,
.stApp [data-baseweb="textarea"] textarea::placeholder {
    color: #993333 !important;
    opacity: 1 !important;
}

.stApp [data-baseweb="select"] { background-color: var(--mf-surface) !important; }
.stApp [data-baseweb="popover"] { background-color: var(--mf-surface) !important; }
.stApp [role="listbox"] { background-color: var(--mf-surface) !important; color: var(--mf-green) !important; }
.stApp [role="option"]:hover { background-color: #002200 !important; color: var(--mf-amber-hi) !important; }

.stApp .stButton button, .stApp .stDownloadButton button {
    background-color: var(--mf-surface) !important;
    color: var(--mf-amber) !important;
    border: 1px solid var(--mf-amber) !important;
    font-family: var(--mf-mono) !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.stApp .stButton button:hover, .stApp .stDownloadButton button:hover {
    background-color: #1a1100 !important;
    color: var(--mf-amber-hi) !important;
    border-color: var(--mf-amber-hi) !important;
}
.stApp .stButton button[kind="primary"],
.stApp .stButton button[kind="primary"] * {
    background-color: #0066CC !important;
    color: #FFFFFF !important;
    border: 1px solid #0066CC !important;
    font-weight: 700 !important;
    text-shadow: 0 0 2px rgba(0, 0, 0, 0.45);
}
.stApp .stButton button[kind="primary"]:hover,
.stApp .stButton button[kind="primary"]:hover * {
    background-color: #1A88FF !important;
    color: #FFFFFF !important;
    border-color: #1A88FF !important;
}
.stApp .stButton button[kind="primary"][disabled],
.stApp .stButton button[kind="primary"][disabled] * {
    background-color: #003366 !important;
    color: #CCE5FF !important;
    border-color: #003366 !important;
    text-shadow: none !important;
}
.stApp .stButton button[disabled], .stApp .stDownloadButton button[disabled] {
    color: var(--mf-green-dim) !important;
    border-color: var(--mf-green-dim) !important;
}

.stApp [data-testid="stMetric"] {
    background-color: var(--mf-surface) !important;
    border: 1px solid var(--mf-border);
    padding: 0.5rem 0.75rem;
}
.stApp [data-testid="stMetricLabel"] { color: var(--mf-amber) !important; }
.stApp [data-testid="stMetricValue"] { color: var(--mf-green) !important; font-family: var(--mf-mono) !important; }

.stApp [data-testid="stExpander"] {
    background-color: var(--mf-surface) !important;
    border: 1px solid var(--mf-border) !important;
    border-radius: 0 !important;
}
.stApp [data-testid="stExpander"] details,
.stApp [data-testid="stExpander"] > div {
    background-color: var(--mf-surface) !important;
}
.stApp [data-testid="stExpander"] summary,
.stApp [data-testid="stExpander"] summary p {
    background-color: var(--mf-surface) !important;
    color: var(--mf-amber) !important;
    font-family: var(--mf-mono) !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border: none !important;
    padding: 0.25rem 0 !important;
}

.stApp [data-testid="stExpanderToggleIcon"],
.stApp [data-testid="stExpanderToggleIcon"] *,
.stApp [data-testid="stIconMaterial"],
.stApp [data-testid="stIconMaterial"] *,
.stApp .material-icons,
.stApp .material-symbols-outlined,
.stApp .material-symbols-rounded,
.stApp .material-symbols-sharp,
.stApp svg, .stApp svg * {
    font-family: 'Material Symbols Outlined','Material Symbols Rounded','Material Symbols Sharp','Material Icons',sans-serif !important;
    text-transform: none !important;
    letter-spacing: normal !important;
    font-weight: normal !important;
}
.stApp [data-testid="stExpanderToggleIcon"],
.stApp [data-testid="stIconMaterial"] {
    color: var(--mf-amber) !important;
}
.stApp [data-testid="stExpanderDetails"] {
    background-color: var(--mf-surface) !important;
    padding: 0.75rem 1rem 1rem 1rem !important;
    border-top: 1px solid var(--mf-border) !important;
}
.stApp [data-testid="stExpanderDetails"] p,
.stApp [data-testid="stExpanderDetails"] li,
.stApp [data-testid="stExpanderDetails"] span {
    color: var(--mf-green) !important;
    font-family: var(--mf-mono) !important;
    line-height: 1.55 !important;
    font-size: 0.95rem !important;
}
.stApp [data-testid="stExpanderDetails"] strong { color: var(--mf-amber-hi) !important; }
.stApp [data-testid="stExpanderDetails"] code {
    background-color: #001a00 !important;
    color: var(--mf-amber-hi) !important;
    padding: 0 0.25rem !important;
    border: 1px solid var(--mf-border) !important;
}
.stApp [data-testid="stExpanderDetails"] ul {
    list-style: none !important;
    padding-left: 0.5rem !important;
}
.stApp [data-testid="stExpanderDetails"] ul li {
    position: relative;
    padding-left: 1.25rem;
}
.stApp [data-testid="stExpanderDetails"] ul li::before {
    content: ">";
    color: var(--mf-amber) !important;
    position: absolute;
    left: 0;
    font-weight: 700;
}

[data-testid="stDataFrame"] thead tr th,
[data-testid="stDataFrame"] [role="columnheader"],
[data-testid="stTable"] thead tr th {
    background-color: #0c0c0c !important;
    color: var(--mf-amber) !important;
    font-family: var(--mf-mono) !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid var(--mf-amber) !important;
}
[data-testid="stDataFrame"] tbody tr td,
[data-testid="stTable"] tbody tr td {
    background-color: var(--mf-bg) !important;
    color: var(--mf-green) !important;
    font-family: var(--mf-mono) !important;
}

.stApp .mf-table-wrap {
    overflow-x: auto;
    border: 1px solid var(--mf-border);
    background-color: var(--mf-bg);
    padding: 0;
    margin-bottom: 0.75rem;
}
.stApp table.mf-findings-table {
    width: 100%;
    border-collapse: collapse;
    font-family: var(--mf-mono) !important;
    font-size: 0.92rem;
    background-color: var(--mf-bg) !important;
}
.stApp table.mf-findings-table thead tr th {
    background-color: #0c0c0c !important;
    color: #FFFF00 !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 0.5rem 0.75rem;
    text-align: left;
    border-bottom: 1px solid var(--mf-border) !important;
    border-right: 1px solid var(--mf-border) !important;
    position: sticky;
    top: 0;
    z-index: 1;
}
.stApp table.mf-findings-table thead tr th:last-child {
    border-right: none !important;
}
.stApp table.mf-findings-table tbody tr td {
    color: var(--mf-green) !important;
    background-color: var(--mf-bg) !important;
    padding: 0.35rem 0.75rem;
    vertical-align: top;
    border-bottom: 1px solid var(--mf-border) !important;
    border-right: 1px solid var(--mf-border) !important;
    white-space: pre-wrap;
    word-break: break-word;
    max-width: 32rem;
}
.stApp table.mf-findings-table tbody tr td:last-child {
    border-right: none !important;
}
.stApp table.mf-findings-table tbody tr:last-child td {
    border-bottom: none !important;
}
.stApp table.mf-findings-table tbody tr:hover td {
    background-color: #061a06 !important;
}

.stApp pre, .stApp code, .stApp .stCodeBlock {
    background-color: var(--mf-surface) !important;
    color: var(--mf-green) !important;
    border: 1px solid var(--mf-border);
    font-family: var(--mf-mono) !important;
}

.stApp [data-testid="stAlert"] {
    background-color: var(--mf-surface) !important;
    border: 1px solid var(--mf-amber) !important;
    color: var(--mf-amber-hi) !important;
    font-family: var(--mf-mono) !important;
}
</style>
"""


_HOW_TO_USE_MD = """
**Goal:** Explore COBOL error-code assignments detected in your sources, with conditions, parameters, mapped fields, and plain-English summaries.

**1. Scan your sources (sidebar → *Scan Input*)**
- **COBOL source root** — folder containing `.cbl` / `.cob` / `.cpy` files.
- **Rules file** — JSON file with `code_length`, error-code fields, and named patterns.
- **Output folder** — where `errors.jsonl`, `manifest.json`, and the markdown table are written.
- **Focused Error Field** *(optional)* — up to **30 characters**. Substring match against **CORORA** and **CORORL** one- and two-char mapping files (e.g. `ERR-NO-SEC-EDD-OVRD` matches `CORORA-R-ERR-…` and `CORORL-R-ERR-…`). Resolves derived two-character codes the same way as focused error-code search, then writes **`error_field_table.md`**. Overrides focused error code when both are filled.
- **Mapping folder** *(optional)* — folder containing `CORORA_*` and `CORORL_*` mapping fragments. Leave blank to auto-detect.
- **Summarizer** — `heuristic` (default) or `openai` (needs `OPENAI_API_KEY`).
- Click **Run scan** to generate or refresh results.

**2. Filter findings (sidebar → *Filters*)**
- **Programs** — multi-select to narrow by program ID.
- **Error codes** — type one or more **2-character** codes (e.g. `E1` or `E1, Q0 QX`). Invalid entries show an inline error.
- **Error field contains** — filter the loaded table by substring in the **Error Field** column (max 30 characters).

**3. Read the results**
- **Metrics** at the top show total findings, distinct programs, distinct codes, and source files.
- **Findings table** — first column `S.No`, then `Error Code`, `Error Field` (the COBOL field/condition the code maps to), program, line, paragraph/section, condition, parameters, message, and a row summary.
- **Download filtered CSV** to export the current view.
- **Finding Details** — pick any row to see its full statement, related variables, program-level summary, and the surrounding COBOL logic context.
"""


def main() -> None:
    st.set_page_config(page_title="Insideline Error Code Dashboard", layout="wide")
    st.markdown(_MAINFRAME_CSS, unsafe_allow_html=True)
    st.title("Insideline Error Code Dashboard")
    st.caption("Explore detected COBOL error codes, conditions, parameters, and generated summaries.")
    if "scan_results_ready" not in st.session_state:
        st.session_state["scan_results_ready"] = False

    with st.expander("How to use this dashboard", expanded=False):
        st.markdown(_HOW_TO_USE_MD)

    _, _, out_dir = render_scan_controls()
    records_path = out_dir / "errors.jsonl"
    manifest_path = out_dir / "manifest.json"

    if st.session_state["scan_results_ready"]:
        manifest = load_manifest(str(manifest_path))
        records = load_records(str(records_path))
    else:
        manifest = {}
        records = []
    frame = records_to_frame(records)

    if st.session_state["scan_results_ready"] and manifest:
        generated_at = manifest.get("generated_at", "")
        scanned_root = manifest.get("root", "")
        st.caption(f"Loaded `{records_path}` from scan root `{scanned_root}`. Generated at `{generated_at}`.")
    elif not st.session_state["scan_results_ready"]:
        st.info("Initial load is clean. Click **RUN SCAN** in the sidebar to populate Findings.")
    else:
        st.warning(f"No manifest found at `{manifest_path}`. Run a scan from the sidebar or with `cobol-scan`.")

    if frame.empty:
        render_metrics(frame)
        st.subheader("Findings")
        st.info("Findings are empty. Run a scan or adjust scan inputs to load fresh results.")
        return

    st.sidebar.header("Filters")
    filtered = apply_filters(frame)

    render_metrics(filtered)
    st.subheader("Findings")
    render_table(filtered)
    render_finding_flowchart_section(filtered)
    render_finding_details(filtered, manifest)


def launch() -> None:
    """Console-script entry point that launches this module with Streamlit."""
    from streamlit.web import cli as streamlit_cli

    sys.argv = ["streamlit", "run", str(Path(__file__).resolve())]
    raise SystemExit(streamlit_cli.main())


if __name__ == "__main__":
    main()
