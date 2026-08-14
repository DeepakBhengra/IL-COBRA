# Legacy Error Code Mapper — Codebase Onboarding

One-page reference for architects and developers onboarding to this repository. Derived from [README.md](../README.md) and the `src/cobol_error_scanner` package. For a fuller architecture and stack overview, see [TECHNICAL_SUMMARY.md](TECHNICAL_SUMMARY.md).

---

## Purpose

Python tool for **COBOL impact analysis** and **legacy modernization**: scan a folder of `.cbl` / `.cob` / `.cpy` sources, detect where error/return codes are set, attach nearby **IF** conditions and message literals when possible, and emit **searchable artifacts** (JSONL, manifest, markdown table). Optional **CORORA/CORORL** mapping enrichment for two-character `E*` codes and **88-level** field queries.

This is a **practical subset** of full COBOL analysis—not a compiler front end.

---

## Entry points — when to use what

| Entry | Console script | Module | Use when |
| ----- | -------------- | ------ | -------- |
| **CLI scan** | `cobol-scan` | `cobol_error_scanner.cli:main` | Batch scans, CI, filtered reports (`-e`, `-f`), writing `out/` artifacts |
| **Dashboard** | `cobol-dashboard` | `cobol_error_scanner.dashboard:launch` | Interactive review: metrics, filters, finding details, Mermaid flowcharts (CDN) |
| **Flowchart** | `cobol-flowchart` | `cobol_error_scanner.flowchart_from_summary:main` | Generate `.mmd` / `.dot` from one summary string or all rows in `errors.jsonl` |
| **Module run** | — | `python -m cobol_error_scanner` | Same as CLI (`__main__.py` → `cli.main`) |

**Dependencies** ([pyproject.toml](../pyproject.toml)): `pydantic`, `typer`, `rich`, `lark`, `pandas`, `streamlit`. OpenAI summarization is optional (`pip install openai`, `OPENAI_API_KEY`).

**Typical CLI commands**

```powershell
py -m pip install -e .
py -m cobol_error_scanner.cli samples -r config\error_rules.json -o out
py -m cobol_error_scanner.cli samples -r config\error_rules.json -o out -e E1
py -m cobol_error_scanner.cli samples -f ERR-NO-SEC-EDD-OVRD -o out
cobol-dashboard
cobol-flowchart out\errors.jsonl -o out\flowcharts
```

---

## Architecture (data flow)

```mermaid
flowchart TB
  subgraph inputs [Inputs]
    cobolRoot[COBOL_source_root]
    rulesJson[config/error_rules.json]
    mapFiles[error_mapping_files]
  end

  subgraph standardScan [Standard scan path]
    scanner[scanner.iter_cobol_files]
    parser[cobol_parse.CobolStructureParser]
    detector[detector.find_assignments + match_rules]
    logic[logic_extractor IF enrichment]
    rowSum[summarizer.summarize_row]
    progSum[summarizer.summarize_program]
    pipeline[pipeline.scan_root]
  end

  subgraph mappingScan [Mapping path CLI only]
    mapResolve[mapping_resolve]
    mapCatalog[mapping_catalog]
  end

  subgraph outputs [Outputs docgen]
    jsonl[errors.jsonl]
    manifest[manifest.json]
    mdTable[errors_table.md / error_table.md / error_field_table.md]
  end

  cobolRoot --> scanner
  scanner --> parser
  parser --> detector
  rulesJson --> detector
  detector --> logic
  logic --> rowSum
  rowSum --> pipeline
  pipeline --> progSum
  progSum --> jsonl
  progSum --> manifest
  progSum --> mdTable

  mapFiles --> mapCatalog
  mapCatalog --> mapResolve
  cobolRoot --> mapResolve
  mapResolve --> progSum

  jsonl --> dashboard[dashboard.py]
  jsonl --> flowchart[flowchart_from_summary.py]
```

### Pipeline stages and module ownership

| Stage | Responsibility | Module |
| ----- | -------------- | ------ |
| 1. Discover files | Recursive `.cbl/.cob/.cpy` under source root | [scanner.py](../src/cobol_error_scanner/scanner.py) |
| 2. Normalize & structure | Fixed-format comment strip; PROCEDURE DIVISION sections/paragraphs | [cobol_parse.py](../src/cobol_error_scanner/cobol_parse.py) |
| 3. Detect assignments | `MOVE`/`SET` into configured fields; regex `error_patterns` | [detector.py](../src/cobol_error_scanner/detector.py) + [error_rules.json](../config/error_rules.json) |
| 4. Enrich logic | Preceding IF, condition text, parameters, message literals in block | [logic_extractor.py](../src/cobol_error_scanner/logic_extractor.py) |
| 5. Summarize | Per-row and per-program text (heuristic or OpenAI) | [summarizer.py](../src/cobol_error_scanner/summarizer.py) |
| 6. Orchestrate | Per-file loop, filter by error code | [pipeline.py](../src/cobol_error_scanner/pipeline.py) |
| 7. Emit artifacts | JSONL rows, full manifest, markdown table | [docgen.py](../src/cobol_error_scanner/docgen.py) |
| Models | `ErrorOccurrence`, `ProgramSummary`, `ScanManifest` | [models.py](../src/cobol_error_scanner/models.py) |

**CLI orchestration** ([cli.py](../src/cobol_error_scanner/cli.py)):

- Default: `scan_root` → optional `filter_programs_by_error_code` (`-e`).
- Two-char `E*` + mapping dir: may use `apply_mapping_filter_fallback` when standard filter is empty or mapping hits exist.
- `--error-field` (`-f`): **skips** general rules scan; calls `resolve_mapped_error_field` only.
- Always: `build_manifest` → `write_jsonl`, `write_manifest_json`, `write_markdown_table`.

**Dashboard** ([dashboard.py](../src/cobol_error_scanner/dashboard.py)) reuses `scan_root`, mapping helpers, and `docgen` writers; loads existing `errors.jsonl` / `manifest.json` after scan.

---

## Configuration and mapping sources

### Detection rules — `config/error_rules.json`

| Key | Role |
| --- | ---- |
| `return_code_fields` | Substrings for numeric targets (e.g. `RETURN-CODE`, `SQLCODE`) |
| `error_code_fields` | Substrings for alphanumeric error codes (e.g. `ERROR-CODE`) |
| `error_message_fields` | Substrings for message text targets |
| `error_patterns` | Named regexes (e.g. `STOP RUN`, `SQLCODE NOT = ZERO`) |
| `code_length` | Optional literal length filter (sample config uses `2`) |

Loaded by `load_detector_config()` in [detector.py](../src/cobol_error_scanner/detector.py). Field matching is **substring/suffix** on uppercased names.

### CORORA / CORORL mappings — `error_mapping_files/`

| File | Loaded by | Purpose |
| ---- | --------- | ------- |
| `CORORA_TWO_CHAR_ERROR.txt` | `load_two_char_value_to_names` | Two-char VALUE → 88-level names (CORORA) |
| `CORORA_ONE_CHAR_ERROR.txt` | `load_one_char_error_type_map` | One-char ERROR-TYPE map |
| `CORORL_TWO_CHAR_ERROR.txt` | same | CORORL family |
| `CORORL_ONE_CHAR_ERROR.txt` | same | CORORL family |

Resolution and COBOL search: [mapping_catalog.py](../src/cobol_error_scanner/mapping_catalog.py), [mapping_resolve.py](../src/cobol_error_scanner/mapping_resolve.py). Directory resolved via `--corora-mappings` or defaults beside source root / cwd.

Mapping findings populate `error_field` and `mapping_detail` on `ErrorOccurrence` (see [models.py](../src/cobol_error_scanner/models.py)).

---

## Output contract

All paths relative to `--out` (default `out/`).

| Artifact | When | Contents |
| -------- | ---- | -------- |
| `errors.jsonl` | Always | One JSON object per finding row (`manifest.to_searchable_records()`) |
| `manifest.json` | Always | Full `ScanManifest`: root, `generated_at`, nested programs + occurrences |
| `errors_table.md` | Full scan (no `-e`/`-f`) | Markdown table of all findings |
| `error_table.md` | `-e CODE` | Filtered by detected code |
| `error_field_table.md` | `-f FIELD` | Mapping-driven field query |

**JSONL row fields** (primary): `program`, `file`, `error_code`, `error_field`, `line`, `paragraph`, `section`, `statement`, `condition`, `parameters`, `error_message`, `row_summary`, `mapping_detail`, `logic_context`, `related`, `summary` (program-level), `search_text`.

**Markdown columns**: Error Code | Error field | Program | Line | Paragraph | Condition | Parameters | Summary | Mapping detail.

---

## Hands-on onboarding sequence

1. **Install & scan sample** — `samples/ORP676.cob`; inspect `out/errors.jsonl`, `manifest.json`, `errors_table.md`.
2. **Trace CLI** — `cli.scan` → `pipeline.scan_root` → per-file loop in [pipeline.py](../src/cobol_error_scanner/pipeline.py).
3. **Rules vs detector** — Edit [error_rules.json](../config/error_rules.json); follow `find_assignments` and `is_error_value_target` in [detector.py](../src/cobol_error_scanner/detector.py).
4. **IF enrichment** — `find_preceding_if_line`, `parse_if_condition_line`, `find_message_literal_in_block` in [logic_extractor.py](../src/cobol_error_scanner/logic_extractor.py).
5. **Schemas** — [models.py](../src/cobol_error_scanner/models.py) + writers in [docgen.py](../src/cobol_error_scanner/docgen.py).
6. **Mapping path** — `resolve_mapped_error_field`, `apply_mapping_filter_fallback` in [mapping_resolve.py](../src/cobol_error_scanner/mapping_resolve.py).
7. **UI** — Sidebar scan + filters + Mermaid in [dashboard.py](../src/cobol_error_scanner/dashboard.py).

---

## Improvement backlog (from README limitations + code review)

| Priority | Area | Suggestion |
| -------- | ---- | ---------- |
| High | Copybook expansion | Preprocess `COPY` or integrate a stronger COBOL parser; current pass reads files as-is |
| High | Multi-line IF | Extend `parse_if_condition_line` / backward IF walk for continued predicates |
| Medium | `lark` grammar | `lark` is a dependency but structure pass is regex-based—either use Lark for PROCEDURE DIVISION or drop unused dep |
| Medium | Rule configurability | Document/customize `code_length` behavior per customer; avoid silent skips when length mismatches |
| Medium | Offline dashboard | Bundle Mermaid locally instead of CDN for air-gapped environments |
| Low | Summaries | Expand heuristic rules in `summarize_row` or standardize OpenAI prompts |
| Low | Flowcharts | Clarify in UI that diagrams are summary sketches, not full CFG |
| Low | Samples | README mentions `cust001.cob` / `demo.cob`; repo currently has `samples/ORP676.cob`—align docs or add samples |
| Low | Tests | Add golden-file tests for `pipeline.scan_root` and mapping resolve on fixed snippets |

---

## Quick file index

```
config/error_rules.json          # Detection field lists + regex patterns
error_mapping_files/             # CORORA/CORORL copybook fragments
samples/                         # Example COBOL (ORP676.cob)
src/cobol_error_scanner/
  cli.py                         # cobol-scan
  pipeline.py                    # scan_root orchestration
  scanner.py                     # File discovery
  cobol_parse.py                 # Sections/paragraphs
  detector.py                    # Rules + MOVE/SET
  logic_extractor.py             # IF blocks, CORORA control-flow enrichment
  summarizer.py                  # Heuristic / OpenAI
  docgen.py                      # JSONL, manifest, markdown
  models.py                      # Pydantic schemas
  mapping_catalog.py             # Load mapping files
  mapping_resolve.py             # Map codes/fields → COBOL hits
  dashboard.py                   # Streamlit UI
  flowchart_from_summary.py      # Mermaid/DOT from summaries
```
