# Legacy Error Code Mapper (COBOL Error Logic Scanner)

Python tool for **impact analysis** and **legacy modernization** on COBOL sources. It walks a folder of programs, finds where error codes and return values are set, ties them to nearby **IF / END-IF** logic when possible, and produces **searchable artifacts** plus a **markdown table** for architects and migration teams.

This is a **practical subset** of full COBOL analysis (not a complete compiler front end). It is designed to be extended with your own field lists, regex rules, and optional LLM summarization.

## How it works

End-to-end flow:

1. **File scanner** — Recursively finds `.cbl`, `.cob`, and `.cpy` under the directory you pass in.
2. **COBOL structure pass** — Normalizes lines (fixed-format aware, best-effort), locates **PROCEDURE DIVISION**, **sections**, and **paragraphs** so each finding can be attributed to a paragraph.
3. **Error detector** — Uses `config/error_rules.json` to decide what counts as an “error” assignment or branch:
   - **Numeric** `MOVE … TO …` / `SET … TO …` into **return-code-style** fields (e.g. `WS-RETURN-CODE`, `SQLCODE`).
   - **Alphanumeric** literals (e.g. `'E102'`) into **error-code** fields (e.g. names containing `ERROR-CODE`).
   - Optional **line patterns** (regex), e.g. `STOP RUN`, `SQLCODE NOT = ZERO`.
4. **Logic extractor** — For assignments into configured error fields, walks **backward** through **IF / END-IF** nesting to attach the **condition** (e.g. `WS-CUST-ID = SPACES`), derives **parameters** (data names in that condition), and scans the same IF block for **message** literals moved into **error-message** fields (e.g. `WS-ERROR-MSG`).
5. **Summarizer** — Builds a short **row summary** (heuristic by default; optional **OpenAI** for program-level narrative if configured).
6. **Report writer** — Emits `errors.jsonl`, `manifest.json`, and a **markdown table** (see below).

The **Streamlit dashboard** and **`cobol-flowchart`** tool can turn each row’s summary (and condition when present) into **Mermaid** control-flow diagrams for review.

### Optional: CORORA / CORORL two-character codes

When you filter by a **two-character code that starts with `E`** (e.g. `E1`, `EV`) and mapping files are available, the tool can use **CORORA** and **CORORL** copybook fragments (`CORORA_TWO_CHAR_ERROR`, `CORORA_ONE_CHAR_ERROR`, `CORORL_TWO_CHAR_ERROR`, `CORORL_ONE_CHAR_ERROR`) to search sources for related **88-level / SET** patterns and enrich or substitute results. Resolution treats **`CORORA-R-*`** and **`CORORL-*`** fields the same way (for example **`CORORA-R-ERROR-TYPE`** and **`CORORL-R-ERROR-TYPE`**, **`…-RECORD-RESPONSE-FLAG`**, **`…-INV-TRANSIT-MODE`**). When the same code appears in **both** families, the **Mapping detail** column (and JSONL `mapping_detail`) explains that. Mapping files are resolved from **`--corora-mappings`** (any folder name; default `error_mapping_files` beside the source tree or cwd). If you do not use these mappings, ordinary **`-e` filtering** on detected codes still applies.

## Configuration

Edit **`config/error_rules.json`**:

| Field | Purpose |
| ----- | ------- |
| `return_code_fields` | Substrings for numeric return / status targets. |
| `error_code_fields` | Substrings for alphanumeric error code targets (e.g. `ERROR-CODE` matches `WS-ERROR-CODE`). |
| `error_message_fields` | Substrings for message text targets (e.g. `ERROR-MSG` matches `WS-ERROR-MSG`). |
| `error_patterns` | Named regexes for extra line-level detections. |
| `code_length` | Optional; used where length rules apply (e.g. CORORA paths). |

## Installation

Requires **Python 3.10+**. On Windows, the **`py`** launcher is often more reliable than **`python`** on PATH.

```powershell
cd c:\Legacy-Error-Code-Mapper
py -m pip install -e .
```

## Usage

Entry points (after **`pip install -e .`**): **`cobol-scan`**, **`cobol-dashboard`**, **`cobol-flowchart`**, or **`py -m cobol_error_scanner.cli`** for the scanner only.

```text
cobol-scan <SOURCE_ROOT> [--rules PATH] [--out DIR] [--summarizer heuristic|openai]
         [--error-code CODE] [--table NAME] [--corora-mappings DIR]
```

### Full scan (all findings)

Writes **`out/errors_table.md`** by default (plus `errors.jsonl`, `manifest.json`).

```powershell
py -m cobol_error_scanner.cli samples -r config\error_rules.json -o out
```

### Filter by error code (single-code report)

Only programs and rows whose **detected code** equals the given value (case-insensitive) are included. The default markdown file is **`error_table.md`** so it is not confused with the full **`errors_table.md`**.

```powershell
py -m cobol_error_scanner.cli samples -r config\error_rules.json -o out -e XX
```

Replace **`XX`** with the two-character code you want from your sources and rules.

Override the table filename:

```powershell
py -m cobol_error_scanner.cli samples -r config\error_rules.json -o out -e XX -t my_report.md
```

### OpenAI summarization (optional)

Install `openai`, set **`OPENAI_API_KEY`**, and use **`--summarizer openai`**.

### Streamlit dashboard

After install, launch the UI with **`cobol-dashboard`** (or `streamlit run src/cobol_error_scanner/dashboard.py` from the repo root). Point the sidebar at your **COBOL source root**, **rules** JSON, and **output folder** (where `errors.jsonl` / `manifest.json` live), then run a scan or open existing outputs.

The dashboard shows metrics, a filterable findings table, **Finding details**, and a **Control flow chart** section: pick **any filtered row** (same order as **S.No** in the table). The chart is built from each row’s **`row_summary`** and, when needed, **`condition`** / **`statement`** from `errors.jsonl`. CORORA-style summaries that begin with `Nested control path (inner to outer):` are turned into a top-down **IF / WHEN** style diagram. The chart loads **Mermaid** from a CDN inside the embedded viewer; use the **+ / − / 1:1** controls (bottom-right of the chart pane) or **Ctrl + scroll wheel** to zoom. The diagram area scrolls independently so zoom controls stay pinned to the corner of the viewer.

### Flow charts (CLI and module)

**`cobol-flowchart`** generates **Mermaid** (`.mmd`) and optional **Graphviz DOT** (`.dot`) from scan output or a pasted summary string. It lives in **`cobol_error_scanner/flowchart_from_summary.py`** and can be run as a module or via the console script.

```powershell
# One diagram from inline summary text
cobol-flowchart -t "Nested control path (inner to outer): IF A -> IF B. MOVE 99 TO X" -o out\my_flow.mmd --dot

# One file per row in errors.jsonl (writes flow_0001.mmd, … under the output directory)
cobol-flowchart out\errors.jsonl -o out\flowcharts
```

Labels are normalized for Mermaid (for example parentheses in COBOL predicates are kept inside quoted node text so diagrams still render).

## Outputs (under `--out`, default `out`)

| File | Description |
| ---- | ----------- |
| `errors_table.md` | Full markdown table (includes **Mapping detail** when mapping rules apply). |
| `error_table.md` | Same columns, produced by default when **`--error-code`** is used (filtered rows only). |
| `errors.jsonl` | One JSON object per row for search, ETL, or dashboards. |
| `manifest.json` | Full structured manifest (programs, occurrences, metadata). |

## Sample programs

Under **`samples/`** (for example **`cust001.cob`**, **`demo.cob`**) you can try the commands above and inspect **`out/`**.

## Project layout

| Path | Role |
| ---- | ---- |
| `src/cobol_error_scanner/scanner.py` | Discover COBOL files. |
| `src/cobol_error_scanner/cobol_parse.py` | Paragraph / section structure. |
| `src/cobol_error_scanner/detector.py` | Rules and MOVE/SET detection. |
| `src/cobol_error_scanner/logic_extractor.py` | IF blocks, conditions, messages. |
| `src/cobol_error_scanner/pipeline.py` | Orchestration and error-code filter. |
| `src/cobol_error_scanner/summarizer.py` | Heuristic / OpenAI summaries. |
| `src/cobol_error_scanner/docgen.py` | JSONL, manifest, markdown table. |
| `src/cobol_error_scanner/mapping_catalog.py` | Load CORORA / CORORL mapping fragments and search needles. |
| `src/cobol_error_scanner/mapping_resolve.py` | Map two-char codes and error-field queries to COBOL hits (CORORA + CORORL). |
| `src/cobol_error_scanner/cli.py` | Typer CLI (`cobol-scan`). |
| `src/cobol_error_scanner/dashboard.py` | Streamlit UI (`cobol-dashboard`). |
| `src/cobol_error_scanner/flowchart_from_summary.py` | Mermaid / DOT flowcharts from summaries (`cobol-flowchart`). |

## Limitations

- COBOL dialects and **copybook expansion** (`COPY`) are only partially modeled; complex source may need preprocessing or stronger parsers for production accuracy.
- **Multi-line IF** conditions are best-effort; single-line `IF` headers are the sweet spot.
- Row **summaries** are heuristics unless you plug in richer AI or rules.
- **Flow charts** are a readable sketch of control flow from summaries and conditions, not a full control-flow graph of the program. The dashboard chart requires network access once to load Mermaid from the CDN.

Contributions and tighter grammars can build on the same pipeline and manifest format.
