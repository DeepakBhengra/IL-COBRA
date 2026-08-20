"""Streamlit dashboard for COBOL error-code scan results."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from cobol_error_scanner.data_access import (
    DETAIL_FIELDS,
    TABLE_COLUMNS,
    filter_frame,
    format_value,
    load_manifest,
    load_records,
    parse_error_code_tokens,
    records_to_frame,
)
from cobol_error_scanner.flowchart_from_summary import build_mermaid, parse_jsonl_row
from cobol_error_scanner.mapping_catalog import MAX_ERROR_FIELD_INPUT_LEN, error_field_query_violation
from cobol_error_scanner.paths import (
    DASHBOARD_PORT,
    DEFAULT_CORORA_MAPPINGS,
    DEFAULT_OUT_DIR,
    DEFAULT_RULES_PATH,
    DEFAULT_SOURCE_ROOT,
    detect_repo_root,
)
from cobol_error_scanner.scan_service import optional_path, run_scan
from cobol_error_scanner.table_export import build_csv_bytes, build_display_table

ENTERPRISE_UI_URL = os.environ.get("ENTERPRISE_UI_URL", "http://localhost:8000")


def apply_filters(frame: pd.DataFrame) -> pd.DataFrame:
    programs = sorted(value for value in frame["program"].dropna().astype(str).unique() if value)
    selected_programs = st.sidebar.multiselect("Programs", programs)

    error_code_input = st.sidebar.text_input(
        "Error codes",
        placeholder="e.g. E1 or E1, X2",
        help="Type one or more 2-character error codes separated by commas or spaces. Case-insensitive.",
        max_chars=64,
    )
    typed_codes, invalid_tokens = parse_error_code_tokens(error_code_input)
    if invalid_tokens:
        st.sidebar.error(
            "Error codes must be exactly 2 characters. Invalid: "
            + ", ".join(f"'{token}'" for token in invalid_tokens)
        )

    query = st.sidebar.text_input("Search", placeholder="condition, parameter, message, paragraph...")
    field_contains = st.sidebar.text_input(
        "Error field contains",
        placeholder="substring of CORORA-R-… / CORORL-R-… / CORORH-R-… name",
        help="Filter loaded rows where the Error Field column contains this text (case-insensitive). Max 30 characters.",
        max_chars=MAX_ERROR_FIELD_INPUT_LEN,
    )
    field_contains_effective = field_contains
    if field_contains.strip():
        field_violation = error_field_query_violation(field_contains)
        if field_violation:
            st.sidebar.error(field_violation)
            field_contains_effective = ""

    return filter_frame(
        frame,
        programs=selected_programs or None,
        error_codes=typed_codes or None,
        query=query,
        field_contains=field_contains_effective,
    )


def render_scan_controls() -> tuple[Path, Path, Path]:
    st.sidebar.header("Scan Input")
    source_root = Path(st.sidebar.text_input("COBOL source root", str(DEFAULT_SOURCE_ROOT)))
    rules_path = Path(st.sidebar.text_input("Rules file", str(DEFAULT_RULES_PATH)))
    out_dir = Path(st.sidebar.text_input("Output folder", str(DEFAULT_OUT_DIR)))
    error_code_raw = st.sidebar.text_input(
        "Focused error code",
        placeholder="optional, e.g. 1C",
        help="Optional. Run a focused scan for exactly one 2-character code, including CORORA/CORORL/CORORH mapping fallback.",
        max_chars=8,
    )
    error_code = error_code_raw.strip()
    error_field_raw = st.sidebar.text_input(
        "Focused Error Field",
        placeholder="e.g. ERR-NO-SEC-EDD-OVRD",
        help=(
            "Optional. Max 30 characters. Substring search in CORORA, CORORL, and CORORH one- and "
            "two-char mapping files (maps ERR-… to CORORA-R-ERR-… / CORORL-R-ERR-… / CORORH-R-ERR-…). "
            "If set, overrides focused error code for this run."
        ),
        max_chars=MAX_ERROR_FIELD_INPUT_LEN,
    )
    error_field = error_field_raw.strip()[:MAX_ERROR_FIELD_INPUT_LEN]
    focused_error: str | None = None
    if error_field:
        field_violation = error_field_query_violation(error_field)
        if field_violation:
            focused_error = field_violation
            st.sidebar.error(focused_error)
        elif error_code:
            st.sidebar.caption("Using **Focused Error Field**; focused error code is ignored for this run.")
    elif error_code and len(error_code) != 2:
        focused_error = (
            f"Focused error code must be exactly 2 characters. "
            f"You entered '{error_code}' ({len(error_code)} character(s))."
        )
        st.sidebar.error(focused_error)

    corora_mappings = optional_path(
        st.sidebar.text_input(
            "Mapping folder",
            str(DEFAULT_CORORA_MAPPINGS),
            help=(
                "Folder containing CORORA_* / CORORL_* / CORORH_* mapping fragments "
                "(e.g. CORORA_TWO_CHAR_ERROR, CORORL_TWO_CHAR_ERROR, CORORH_TWO_CHAR_ERROR). "
                "Leave blank to auto-detect."
            ),
        )
    )
    summarizer = st.sidebar.selectbox("Summarizer", ["heuristic", "openai", "ollama"])

    if st.sidebar.button("Run scan", type="primary", disabled=focused_error is not None):
        if focused_error is not None:
            st.sidebar.error(focused_error)
        else:
            try:
                st.session_state["scan_results_ready"] = False
                st.session_state["scan_records"] = []
                st.session_state["scan_manifest"] = {}
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
                records_path = out_dir / "errors.jsonl"
                manifest_path = out_dir / "manifest.json"
                st.session_state["scan_records"] = load_records(records_path)
                st.session_state["scan_manifest"] = load_manifest(manifest_path)
                st.session_state["scan_results_ready"] = True
                st.sidebar.success(
                    f"Scanned {program_count} program(s), found {finding_count} finding(s). Wrote {table_name}."
                )
            except Exception as exc:
                st.session_state["scan_results_ready"] = False
                st.session_state["scan_records"] = []
                st.session_state["scan_manifest"] = {}
                st.sidebar.error(f"Scan failed: {exc}")

    return source_root, rules_path, out_dir


def render_metrics(frame: pd.DataFrame) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Findings", len(frame))
    col2.metric("Programs", frame["program"].nunique())
    col3.metric("Error codes", frame["error_code"].nunique())
    col4.metric("Source files", frame["file"].nunique())


def render_table(filtered: pd.DataFrame) -> None:
    table = build_display_table(filtered)
    table_html = table.to_html(index=False, escape=True, classes="mf-findings-table")
    st.markdown(
        f'<div class="mf-table-wrap">{table_html}</div>',
        unsafe_allow_html=True,
    )
    st.download_button(
        "Download filtered CSV",
        build_csv_bytes(filtered),
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
    row = filtered.iloc[position]
    sn = position + 1
    code = format_value(row.get("error_code", ""))
    prog = format_value(row.get("program", ""))
    ln = format_value(row.get("line", ""))
    return f"Finding {sn}: {code} | {prog} | line {ln}"


def render_finding_flowchart_section(filtered: pd.DataFrame) -> None:
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
        value = format_value(row.get(key, ""))
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

.mf-ui-switch {
    text-align: right;
    margin-bottom: 0.5rem;
}
.mf-ui-switch a {
    color: #1A88FF !important;
    text-decoration: none;
    font-size: 0.9rem;
}
.mf-ui-switch a:hover {
    text-decoration: underline;
    color: #66B3FF !important;
}
</style>
"""


_HOW_TO_USE_MD = """
**Goal:** Explore COBOL error-code assignments detected in your sources, with conditions, parameters, mapped fields, and plain-English summaries.

**1. Scan your sources (sidebar → *Scan Input*)**
- **COBOL source root** — folder containing `.cbl` / `.cob` / `.cpy` files.
- **Rules file** — JSON file with `code_length`, error-code fields, and named patterns.
- **Output folder** — where `errors.jsonl`, `manifest.json`, and the markdown table are written.
- **Focused Error Field** *(optional)* — up to **30 characters**. Substring match against **CORORA**, **CORORL**, and **CORORH** one- and two-char mapping files (e.g. `ERR-NO-SEC-EDD-OVRD` matches `CORORA-R-ERR-…`, `CORORL-R-ERR-…`, and `CORORH-R-ERR-…`). Resolves derived two-character codes the same way as focused error-code search, then writes **`error_field_table.md`**. Overrides focused error code when both are filled.
- **Mapping folder** *(optional)* — folder containing `CORORA_*`, `CORORL_*`, and `CORORH_*` mapping fragments. Leave blank to auto-detect.
- **Summarizer** — `heuristic` (default), `openai` (needs `OPENAI_API_KEY`), or `ollama` (local server at `localhost:11434`).
- Click **Run scan** to generate or refresh results.

**2. Filter findings (sidebar → *Filters*)**
- **Programs** — multi-select to narrow by program ID.
- **Error codes** — type one or more **2-character** codes (e.g. `E1` or `E1, Q0 QX`). Invalid entries show an inline error.
- **Error field contains** — filter the loaded table by substring in the **Error Field** column (max 30 characters).

**3. Read the results**
- **Metrics** at the top show total findings, distinct programs, distinct codes, and source files.
- **Findings table** — first column `S.No`, then `Error Code`, `Error Field` (the COBOL field/condition the code maps to), program, line, paragraph/section, condition, parameters, message, and a row summary.
- **Download filtered CSV** to export the current view.
- **Finding Details** — pick any row to see its full statement, program-level summary, and control flow chart.
"""


def main() -> None:
    st.set_page_config(page_title="Insideline Error Code Dashboard", layout="wide")
    st.markdown(_MAINFRAME_CSS, unsafe_allow_html=True)
    st.markdown(
        f'<div class="mf-ui-switch"><a href="{ENTERPRISE_UI_URL}" target="_blank">Switch to Enterprise UI ↗</a></div>',
        unsafe_allow_html=True,
    )
    st.title("Insideline Error Code Dashboard")
    st.caption("Explore detected COBOL error codes, conditions, parameters, and generated summaries.")
    if "scan_results_ready" not in st.session_state:
        st.session_state["scan_results_ready"] = False
    if "scan_records" not in st.session_state:
        st.session_state["scan_records"] = []
    if "scan_manifest" not in st.session_state:
        st.session_state["scan_manifest"] = {}

    with st.expander("How to use this dashboard", expanded=False):
        st.markdown(_HOW_TO_USE_MD)

    _, _, out_dir = render_scan_controls()
    records_path = out_dir / "errors.jsonl"
    manifest_path = out_dir / "manifest.json"

    if st.session_state["scan_results_ready"]:
        manifest = st.session_state.get("scan_manifest") or {}
        records = st.session_state.get("scan_records") or []
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
    import os as _os

    from streamlit.web import cli as streamlit_cli

    _os.chdir(detect_repo_root())
    sys.argv = [
        "streamlit",
        "run",
        str(Path(__file__).resolve()),
        "--server.port",
        str(DASHBOARD_PORT),
    ]
    raise SystemExit(streamlit_cli.main())


if __name__ == "__main__":
    main()
