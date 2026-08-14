# Legacy Error Code Mapper (COBOL Error Logic Scanner)

Python tool for **impact analysis** and **legacy modernization** on COBOL sources. It walks a folder of programs, finds where error codes and return values are set, ties them to nearby **IF / END-IF** logic when possible, and produces **searchable artifacts** plus a **markdown table** for architects and migration teams.

It can also **ingest operational documents** (runbooks, tickets, emails, incidents), **link** them to COBOL findings, suggest **resolutions** from combined code and document context, and **remember analyst feedback** (confirmed resolutions and accepted evidence) in a persistent knowledge store.

This is a **practical subset** of full COBOL analysis (not a complete compiler front end). It is designed to be extended with your own field lists, regex rules, and optional LLM summarization.

**Documentation:** [Technical summary](docs/TECHNICAL_SUMMARY.md) (architecture, stack, APIs) · [Codebase onboarding](docs/CODEBASE_ONBOARDING.md) (entry points and quick commands)

## How it works

End-to-end flow:

1. **File scanner** — Recursively finds `.cbl`, `.cob`, and `.cpy` under the directory you pass in.
2. **COBOL structure pass** — Normalizes lines (fixed-format aware, best-effort), locates **PROCEDURE DIVISION**, **sections**, and **paragraphs** so each finding can be attributed to a paragraph.
3. **Error detector** — Uses `config/error_rules.json` to decide what counts as an “error” assignment or branch:
   - **Numeric** `MOVE … TO …` / `SET … TO …` into **return-code-style** fields (e.g. `WS-RETURN-CODE`, `SQLCODE`).
   - **Alphanumeric** literals (e.g. `'E102'`) into **error-code** fields (e.g. names containing `ERROR-CODE`).
   - Optional **line patterns** (regex), e.g. `STOP RUN`, `SQLCODE NOT = ZERO`.
4. **Logic extractor** — For assignments into configured error fields, walks **backward** through **IF / END-IF** nesting to attach the **condition** (e.g. `WS-CUST-ID = SPACES`), derives **parameters** (data names in that condition), and scans the same IF block for **message** literals moved into **error-message** fields (e.g. `WS-ERROR-MSG`).
5. **Summarizer** — Builds a short **row summary** (heuristic by default; optional **OpenAI** or **Ollama** for program-level narrative if configured).
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

Entry points (after **`pip install -e .`**): **`cobol-scan`**, **`cobol-ingest`**, **`cobol-dashboard`**, **`cobol-dashboard-api`**, **`cobol-flowchart`**, or **`py -m cobol_error_scanner.cli`** for the scanner only.

For PDF, Word, and richer HTML ingest, also install optional dependencies:

```powershell
py -m pip install -e ".[documents]"
```

```text
cobol-scan <SOURCE_ROOT> [--rules PATH] [--out DIR] [--summarizer heuristic|openai|ollama]
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

### Ollama summarization (local LLM, optional)

Run summaries locally with [Ollama](https://ollama.com) — no API key required.

1. Install Ollama and pull the default model: `ollama pull llama3.2`
2. Ensure the Ollama server is running (default: **http://localhost:11434**)
3. Scan with **`--summarizer ollama`** or set Summarizer to **ollama** in the Enterprise / Classic UI

```powershell
cobol-scan samples --summarizer ollama
cobol-ingest samples\docs --scan-out out -o out --resolver ollama
```

Optional environment variables:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.2` | Model name passed to Ollama |

If Ollama is unavailable, the tool falls back to heuristic summaries (same as OpenAI when the API call fails).

You can also set `"provider": "ollama"` and `"model": "llama3.2"` under **`resolver`** in **`config/app_config.json`** for ingest defaults.

### Operational document ingestion

After a COBOL scan produces **`out/errors.jsonl`**, ingest supporting material from a folder — emails, tickets, PDFs, runbooks, chat exports, incidents, and similar files. Ingestion links each document to COBOL findings and produces resolution summaries for architects and support teams.

**Prerequisite:** run **`cobol-scan`** first so **`errors.jsonl`** exists in the output folder.

```powershell
cobol-ingest <DOCS_FOLDER> --scan-out out -o out
```

Configuration defaults live in **`config/app_config.json`** (knowledge store under **`knowledge/`**, ingest limits, resolver settings). Override with **`COBOL_APP_CONFIG`** pointing at another JSON file.

```powershell
py -m cobol_error_scanner.ingestion.cli samples\docs --scan-out out -o out --resolver heuristic
```

Optional flags:

| Flag | Purpose |
| ---- | ------- |
| `--resolver heuristic` | Default; rule-based resolution from linked COBOL + document context. |
| `--resolver openai` | LLM-backed summaries when **`OPENAI_API_KEY`** is set and `openai` is installed. |
| `--resolver ollama` | Local LLM summaries via Ollama (default model **`llama3.2`**; no API key). |
| `--redact` | Redact email addresses and SSN-like patterns in document bodies. |

**Supported formats** (auto-detected by extension and content): PDF, Word (`.docx`), HTML (including Confluence exports), email (`.eml`), Jira/ticket JSON, chat JSON, CSV/Excel, plain text, logs, and runbooks. See **`samples/docs/`** for examples.

**How documents are linked to findings**

1. **Extract** — Each file is parsed into an **`OperationalDocument`** (title, body, chunks, search text, doc type).
2. **Entity extraction** — Error codes, program names, and field references are pulled from document text using the same rules JSON as the COBOL scanner.
3. **Term matching** — When a focused error code or field is set (via scan filter or ingest options), documents must match strict terms from the current **`errors.jsonl`**; unmatched docs are skipped for resolution.
4. **Link** — Matched documents receive **`DocumentLink`** records tying them to specific finding keys (program + error code + field + line + paragraph).

**Outputs** (under **`--out`**, alongside scan artifacts):

| File | Description |
| ---- | ----------- |
| `documents.jsonl` | One JSON object per ingested document (metadata, links, body preview). |
| `resolutions.jsonl` | Per-document and per-finding resolution suggestions (summary, steps, evidence, confidence). |
| `documents_table.md` | Markdown overview of documents, links, and resolution summaries. |

**Knowledge store** — When **`merge_on_write`** is enabled (default), each ingest run also updates **`knowledge/`**:

| File | Role |
| ---- | ---- |
| `documents.jsonl` | Persistent copy of all ingested documents (incremental re-use). |
| `resolutions.jsonl` | Cross-run resolution history with `proposed` / `accepted` status. |
| `code_field_index.json` | Per error-code index: linked docs, aggregated steps, user feedback. |
| `ingest_index.json` | File-path → document-id map for incremental ingest. |
| `evidence_feedback.jsonl` | Audit log when analysts accept operational evidence. |
| `confirmed_resolutions.jsonl` | Audit log when analysts confirm a resolution in the UI. |
| `user_fixes.jsonl` | Audit log for per-finding fix notes from the COBOL Findings tab. |

Re-run ingestion after changing the focused scan error code so operational docs align with the new findings.

### Resolution logic

Resolution suggestions combine COBOL scan results, operational documents, and accumulated knowledge. The resolver is configured in **`config/app_config.json`** (`resolver.provider`: **`heuristic`**, **`openai`**, or **`ollama`**).

**Heuristic resolver** (default) builds each suggestion from:

1. **User feedback (highest priority)** — If high-confidence **accepted evidence** or a **confirmed resolution** exists for the error code, those steps and excerpts are prepended first.
2. **Linked COBOL finding** — Program, condition, row summary, and mapping detail from **`errors.jsonl`**.
3. **Similar documents** — Token overlap on error codes, programs, and shared vocabulary (top-k from config).
4. **Knowledge index** — Aggregated steps and document excerpts from prior ingest runs for the same code.
5. **Historical resolutions** — Prior `resolutions.jsonl` rows for matching codes (prefers `accepted` status).

When no operational document matches but COBOL findings exist, a **finding-level fallback** resolution is generated from scan data alone (e.g. “Review program X for error code Y — no matching operational documents”).

**OpenAI resolver** — When **`--resolver openai`** is set and **`OPENAI_API_KEY`** is available, the tool attempts an LLM summary per document; it falls back to the heuristic path if the API call fails.

**Ollama resolver** — When **`--resolver ollama`** is set and a local Ollama server is reachable, the tool uses the same LLM prompt path with your configured model (default **`llama3.2`**); it falls back to heuristics if Ollama is down.

**Focused vs full ingest**

| Mode | When | Behavior |
| ---- | ---- | -------- |
| Focused | Scan or ingest filtered by error code / field | Only term-matched documents get resolutions; knowledge index and fast-path reuse apply. |
| Full | No filter; single code in scan | Auto-scopes to that code when exactly one error code is present. |
| Unscoped | Multiple codes, no filter | Links all documents; broader entity matching. |

**Fast path** — If an analyst has already accepted evidence for a focused code (`skip_full_doc_scan_when_accepted` in config), re-ingest can skip the folder walk and reuse confirmed resolutions from the knowledge store.

**Per-finding view in the Enterprise UI** — The Operational docs panel shows a rolled-up summary plus per-document **Historical Resolution** (excerpt from the operational doc) and **Technical Resolution** (structured COBOL fields: program, condition, statement, mapping detail, etc.).

### User feedback

Analyst feedback is stored per error code in **`knowledge/code_field_index.json`** and influences future ingest runs and resolution text.

| Mechanism | Where | What it does |
| --------- | ----- | ------------ |
| **Confirmed resolution** | Enterprise UI → Operational docs panel | Analyst selects a **Historical Resolution** excerpt or a **Condition** token from the linked COBOL finding, adds an optional comment, and saves. Stored under `confirmed_resolution` for that error code. Latest confirm wins. |
| **Accepted evidence** | Knowledge store API (backend) | Analyst marks one or more operational-document evidence items as the confirmed fix. Sets resolution status to `accepted`, enables ingest fast-path, and appends to `evidence_feedback.jsonl`. COBOL-only evidence must use the Findings-tab fix instead. |
| **User fix** | Knowledge store API (backend) | Free-text fix note tied to a specific finding occurrence (program + line). Stored in `user_fixes` and audited in `user_fixes.jsonl`. |

**Confirming a resolution in the Enterprise UI**

1. Open a finding row → **Operational docs** tab.
2. Under a linked document, choose **Historical Resolution** (operational excerpt) or **Condition** (COBOL predicate token).
3. Confirm in the modal; optional analyst comment is saved with the selection.
4. Re-run ingest (or open the finding again) — confirmed text is injected at the top of resolution steps as `Confirmed resolution (Historical Resolution): …` or `Confirmed resolution (Condition): …`.

Confirmed and accepted feedback persists across runs when **`index_by_code_field`** and **`merge_on_write`** are enabled (defaults in **`config/app_config.json`**).

### Streamlit dashboard (Classic UI)

After install, launch the **Classic terminal-style UI** with **`cobol-dashboard`** (or `streamlit run src/cobol_error_scanner/dashboard.py` from the repo root). The app listens on **http://localhost:8504** (see `.streamlit/config.toml`). Point the sidebar at your **COBOL source root**, **rules** JSON, and **output folder** (where `errors.jsonl` / `manifest.json` live), then run a scan or open existing outputs.

Use **Switch to Enterprise UI** in the header to open the new light dashboard (default **http://localhost:8000**). Set **`ENTERPRISE_UI_URL`** to override that link.

The dashboard shows metrics, a filterable findings table, **Finding details**, and a **Control flow chart** section: pick **any filtered row** (same order as **S.No** in the table). The chart is built from each row’s **`row_summary`** and, when needed, **`condition`** / **`statement`** from `errors.jsonl`. CORORA-style summaries that begin with `Nested control path (inner to outer):` are turned into a top-down **IF / WHEN** style diagram. The chart loads **Mermaid** from a CDN inside the embedded viewer; use the **+ / − / 1:1** controls (bottom-right of the chart pane) or **Ctrl + scroll wheel** to zoom. The diagram area scrolls independently so zoom controls stay pinned to the corner of the viewer.

### Enterprise dashboard (React UI)

The **Enterprise UI** is a React + Vite single-page app backed by a **FastAPI** server. It matches a light, flat enterprise table layout: tabbed findings, keyword search, filter drawer, paginated table, row detail with Mermaid flowchart, and scan settings.

**Development** (two terminals):

```powershell
# Terminal 1 — API on http://127.0.0.1:8000
cobol-dashboard-api

# Terminal 2 — Vite dev server on http://localhost:5173 (proxies /api to the API)
cd web
npm install
npm run dev
```

Open **http://localhost:5173** during development. Use **Switch to Classic UI** in the header to return to Streamlit (**http://localhost:8501** by default). Set **`CLASSIC_UI_URL`** (API / Enterprise) or **`ENTERPRISE_UI_URL`** (Streamlit) to customize those links.

**Production** (single process serves the built SPA + API):

```powershell
cd web
npm run build
cobol-dashboard-api
```

Open **http://127.0.0.1:8000**. Optional env vars: **`COBOL_OUT_DIR`** (output folder for `errors.jsonl`), **`COBOL_API_HOST`**, **`COBOL_API_PORT`**.

The Enterprise UI reads the same **`errors.jsonl`** and **`manifest.json`** as the Classic dashboard and supports the same filters (programs, 2-char error codes, error-field substring, full-text search) plus tab views (All / Two-char / Patterns / Mapped). Each finding row includes an **Operational docs** panel (linked documents, resolution summary, confirm-resolution workflow) and **Scan Settings** can trigger document ingest from a server-side folder.

#### External lookup API

The same FastAPI server also exposes an authenticated external endpoint for scan-and-return use cases:

```text
POST /api/v1/lookup
```

Headers:

- **`X-API-Key`** — must match **`COBOL_EXTERNAL_API_KEY`**
- **`X-Application-Key`** — must match **`COBOL_EXTERNAL_APPLICATION_KEY`**

Set the keys before starting the API:

```powershell
$env:COBOL_EXTERNAL_API_KEY = "your-secret"
$env:COBOL_EXTERNAL_APPLICATION_KEY = "your-app-id"
cobol-dashboard-api
```

Request body accepts **exactly one** of **`error_code`** or **`error_field`**:

```json
{
  "error_code": "SE",
  "error_field": "",
  "source_root": "C:/Legacy-Error-Code-Mapper-ver1/samples",
  "rules_path": "C:/Legacy-Error-Code-Mapper-ver1/config/error_rules.json",
  "out_dir": "",
  "corora_mappings": "C:/Legacy-Error-Code-Mapper-ver1/error_mapping_files"
}
```

Example call:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/lookup `
  -H "Content-Type: application/json" `
  -H "X-API-Key: your-secret" `
  -H "X-Application-Key: your-app-id" `
  -d '{"error_code":"SE"}'
```

The response returns all matching findings in one payload with:

- **`error_code`**
- **`error_field`**
- **`program`**
- **`line`**
- **`paragraph`**
- **`condition`**
- **`summary`**
- **`historical_resolution`**

**Historical Resolution prerequisite:** the endpoint does **not** auto-run ingest. To populate **`historical_resolution`**, first run **`cobol-ingest`** (or use the dashboard ingest flow) so **`documents.jsonl`**, **`resolutions.jsonl`**, or the **`knowledge/`** store already exist on the server.

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

### COBOL scan

| File | Description |
| ---- | ----------- |
| `errors_table.md` | Full markdown table (includes **Mapping detail** when mapping rules apply). |
| `error_table.md` | Same columns, produced by default when **`--error-code`** is used (filtered rows only). |
| `errors.jsonl` | One JSON object per row for search, ETL, or dashboards. |
| `manifest.json` | Full structured manifest (programs, occurrences, metadata). |

### Operational document ingest (after `cobol-ingest`)

| File | Description |
| ---- | ----------- |
| `documents.jsonl` | Ingested documents with links to COBOL findings. |
| `resolutions.jsonl` | Resolution suggestions per document and per finding. |
| `documents_table.md` | Markdown table of documents, links, and summaries. |

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
| `src/cobol_error_scanner/summarizer.py` | Heuristic / OpenAI / Ollama summaries. |
| `src/cobol_error_scanner/llm_client.py` | Shared chat-completion client for OpenAI and Ollama. |
| `src/cobol_error_scanner/docgen.py` | JSONL, manifest, markdown table. |
| `src/cobol_error_scanner/mapping_catalog.py` | Load CORORA / CORORL mapping fragments and search needles. |
| `src/cobol_error_scanner/mapping_resolve.py` | Map two-char codes and error-field queries to COBOL hits (CORORA + CORORL). |
| `src/cobol_error_scanner/cli.py` | Typer CLI (`cobol-scan`). |
| `src/cobol_error_scanner/dashboard.py` | Streamlit Classic UI (`cobol-dashboard`). |
| `src/cobol_error_scanner/api/server.py` | FastAPI backend for Enterprise UI (`cobol-dashboard-api`). |
| `src/cobol_error_scanner/data_access.py` | Load/filter findings (shared by Classic + Enterprise). |
| `src/cobol_error_scanner/scan_service.py` | Run scans (shared by Classic + Enterprise). |
| `web/` | React Enterprise dashboard (Vite + TypeScript). |
| `src/cobol_error_scanner/flowchart_from_summary.py` | Mermaid / DOT flowcharts from summaries (`cobol-flowchart`). |
| `src/cobol_error_scanner/ingestion/` | Operational doc adapters, linker, resolution, pipeline (`cobol-ingest`). |
| `src/cobol_error_scanner/ingestion/knowledge_store.py` | Persistent knowledge index, user feedback, cross-run history. |
| `src/cobol_error_scanner/ingestion/resolution.py` | Heuristic / OpenAI resolution suggestion logic. |
| `src/cobol_error_scanner/document_access.py` | Load operational docs and resolutions for dashboard APIs. |
| `src/cobol_error_scanner/ingest_service.py` | Shared ingest runner (CLI + Enterprise API). |
| `config/app_config.json` | Ingest limits, knowledge store, resolver provider settings. |
| `knowledge/` | Persistent store for documents, resolutions, and analyst feedback. |
| `samples/docs/` | Sample operational documents for ingest demos. |

## Limitations

- COBOL dialects and **copybook expansion** (`COPY`) are only partially modeled; complex source may need preprocessing or stronger parsers for production accuracy.
- **Multi-line IF** conditions are best-effort; single-line `IF` headers are the sweet spot.
- Row **summaries** are heuristics unless you plug in richer AI or rules.
- **Flow charts** are a readable sketch of control flow from summaries and conditions, not a full control-flow graph of the program. The dashboard chart requires network access once to load Mermaid from the CDN.

Contributions and tighter grammars can build on the same pipeline and manifest format.
