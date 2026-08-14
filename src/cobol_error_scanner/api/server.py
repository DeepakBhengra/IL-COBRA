"""FastAPI server for the enterprise COBOL scanner dashboard."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from cobol_error_scanner.api.auth import verify_external_api_keys
from cobol_error_scanner.api.lookup_service import build_lookup_response
from cobol_error_scanner.data_access import (
    TabFilter,
    compute_metrics,
    compute_tab_counts,
    filter_frame,
    format_value,
    load_manifest,
    load_records,
    paginate_frame,
    parse_error_code_tokens,
    program_summary_for,
    records_to_frame,
)
from cobol_error_scanner.document_access import get_operational_docs_for_finding, ingest_status
from cobol_error_scanner.ingestion.knowledge_store import set_confirmed_resolution
from cobol_error_scanner.flowchart_from_summary import build_mermaid, parse_jsonl_row
from cobol_error_scanner.ingest_service import run_ingest
from cobol_error_scanner.paths import DASHBOARD_PORT, DEFAULT_OUT_DIR, detect_repo_root
from cobol_error_scanner.scan_service import default_config, optional_path, run_scan
from cobol_error_scanner.table_export import build_csv_bytes

REPO_ROOT = detect_repo_root()
CLASSIC_UI_URL = os.environ.get("CLASSIC_UI_URL", f"http://localhost:{DASHBOARD_PORT}")


def _resolve_web_dist() -> Path:
    """Directory with built React assets (web/dist)."""
    override = os.environ.get("COBOL_WEB_DIST", "").strip()
    if override:
        return Path(override).resolve()
    primary = REPO_ROOT / "web" / "dist"
    if primary.is_dir():
        return primary
    # Editable src layout: .../repo/src/cobol_error_scanner/api/server.py
    here = Path(__file__).resolve().parent
    alt = here.parent.parent.parent / "web" / "dist"
    if alt.is_dir():
        return alt
    return primary


WEB_DIST = _resolve_web_dist()

_NO_CACHE_HEADERS = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}

_out_dir = Path(os.environ.get("COBOL_OUT_DIR", str(DEFAULT_OUT_DIR)))


def _filter_findings(frame: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    try:
        return filter_frame(frame, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ScanRequest(BaseModel):
    source_root: str
    rules_path: str
    out_dir: str = Field(default_factory=lambda: str(DEFAULT_OUT_DIR))
    summarizer: str = "heuristic"
    error_code: str = ""
    error_field: str = ""
    corora_mappings: str = ""


class ScanResponse(BaseModel):
    program_count: int
    finding_count: int
    table_name: str


class IngestRequest(BaseModel):
    docs_root: str
    out_dir: str = Field(default_factory=lambda: str(DEFAULT_OUT_DIR))
    rules_path: str = ""
    resolver: str = "heuristic"
    error_code: str = ""
    error_field: str = ""
    redact: bool = False


class IngestResponse(BaseModel):
    document_count: int
    linked_count: int
    resolution_count: int


class ConfirmedResolutionRequest(BaseModel):
    selected_text: str
    comment: str = ""
    source: Literal["historical", "condition"]


class LookupRequest(BaseModel):
    error_code: str = ""
    error_field: str = ""
    source_root: str = ""
    rules_path: str = ""
    out_dir: str = ""
    corora_mappings: str = ""
    summarizer: str = "heuristic"


class LookupFinding(BaseModel):
    error_code: str
    error_field: str
    program: str
    line: int | None = None
    paragraph: str
    condition: str
    summary: str
    historical_resolution: str


class LookupResponse(BaseModel):
    query: dict[str, str]
    program_count: int
    finding_count: int
    findings: list[LookupFinding]


def _get_out_dir() -> Path:
    return _out_dir


def _set_out_dir(path: Path) -> None:
    global _out_dir
    _out_dir = path


def _resolve_out_dir(out_dir: str | None = None) -> Path:
    raw = (out_dir or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _get_out_dir().resolve()


def _load_frame(out_dir: Path | None = None) -> pd.DataFrame:
    target = out_dir or _get_out_dir()
    records = load_records(target / "errors.jsonl")
    return records_to_frame(records)


def _require_finding(frame: pd.DataFrame, index: int) -> pd.Series:
    if index not in frame.index:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Finding index {index} is not in the current scan "
                f"({len(frame)} row(s)). Close the detail panel and open the finding again "
                f"after your latest scan."
            ),
        )
    return frame.loc[index]


def _row_to_dict(row: pd.Series) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.to_dict().items():
        if isinstance(value, float) and pd.isna(value):
            result[key] = ""
        elif hasattr(value, "item"):
            try:
                result[key] = value.item()
            except (ValueError, AttributeError):
                result[key] = value
        else:
            result[key] = value
    return result


def create_app() -> FastAPI:
    app = FastAPI(title="COBOL Error Scanner API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config/defaults")
    def config_defaults() -> dict[str, str]:
        cfg = default_config()
        cfg["classic_ui_url"] = CLASSIC_UI_URL
        cfg["out_dir"] = str(_get_out_dir())
        return cfg

    @app.get("/api/manifest")
    def get_manifest(out_dir: str | None = None) -> dict[str, Any]:
        target = _resolve_out_dir(out_dir)
        manifest = load_manifest(target / "manifest.json")
        if not manifest:
            raise HTTPException(status_code=404, detail="Manifest not found")
        return manifest

    @app.get("/api/metrics")
    def get_metrics(
        q: str = "",
        programs: list[str] = Query(default=[]),
        error_codes: str = "",
        field_contains: str = "",
        tab: TabFilter = "all",
        out_dir: str | None = None,
    ) -> dict[str, Any]:
        target = _resolve_out_dir(out_dir)
        frame = _load_frame(target)
        codes, _ = parse_error_code_tokens(error_codes)
        filtered = _filter_findings(
            frame,
            programs=programs or None,
            error_codes=codes or None,
            query=q,
            field_contains=field_contains,
            tab=tab,
        )
        return {
            "metrics": compute_metrics(filtered),
            "tab_counts": compute_tab_counts(frame),
            "programs": sorted(
                value for value in frame["program"].dropna().astype(str).unique() if value
            ),
        }

    @app.get("/api/findings")
    def get_findings(
        q: str = "",
        programs: list[str] = Query(default=[]),
        error_codes: str = "",
        field_contains: str = "",
        tab: TabFilter = "all",
        page: int = 1,
        page_size: int = 100,
        sort: str | None = None,
        sort_dir: Literal["asc", "desc"] = "asc",
        out_dir: str | None = None,
    ) -> dict[str, Any]:
        target = _resolve_out_dir(out_dir)
        frame = _load_frame(target)
        codes, invalid = parse_error_code_tokens(error_codes)
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Error codes must be exactly 2 characters. Invalid: {', '.join(invalid)}",
            )
        filtered = _filter_findings(
            frame,
            programs=programs or None,
            error_codes=codes or None,
            query=q,
            field_contains=field_contains,
            tab=tab,
        )
        page_frame, total, total_pages = paginate_frame(
            filtered, page=page, page_size=page_size, sort=sort, sort_dir=sort_dir
        )
        rows = [_row_to_dict(page_frame.iloc[i]) for i in range(len(page_frame))]
        for i, row in enumerate(rows):
            row["_index"] = int(page_frame.index[i])
            row["_page_row"] = (page - 1) * page_size + i
        return {
            "rows": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    @app.get("/api/findings/{index}")
    def get_finding(index: int, out_dir: str | None = None) -> dict[str, Any]:
        target = _resolve_out_dir(out_dir)
        frame = _load_frame(target)
        row = _row_to_dict(_require_finding(frame, index))
        manifest = load_manifest(target / "manifest.json")
        row["program_summary"] = program_summary_for(manifest, str(row.get("program", "")))
        return row

    @app.get("/api/flowchart")
    def get_flowchart(index: int, out_dir: str | None = None) -> dict[str, str]:
        target = _resolve_out_dir(out_dir)
        frame = _load_frame(target)
        row = _require_finding(frame, index)
        rec = {k: ("" if (isinstance(v, float) and pd.isna(v)) else v) for k, v in row.to_dict().items()}
        parsed = parse_jsonl_row(rec)
        title_bits = [
            str(rec.get("program") or ""),
            str(rec.get("error_code") or ""),
            str(rec.get("line") or ""),
        ]
        title = " — ".join(b for b in title_bits if b) or f"Finding {index}"
        chart = build_mermaid(parsed, outcome_title=title)
        return {"chart": chart, "title": title}

    @app.get("/api/findings/{index}/operational-docs")
    def get_finding_operational_docs(index: int, out_dir: str | None = None) -> dict[str, Any]:
        target = _resolve_out_dir(out_dir)
        frame = _load_frame(target)
        row = _row_to_dict(_require_finding(frame, index))
        return get_operational_docs_for_finding(row, target)

    @app.post("/api/findings/{index}/confirmed-resolution")
    def post_confirmed_resolution(
        index: int,
        body: ConfirmedResolutionRequest,
        out_dir: str | None = None,
    ) -> dict[str, Any]:
        # #region agent log
        import json as _json
        import time as _time

        def _dbg(msg: str, data: dict) -> None:
            try:
                with open(
                    r"C:\Legacy-Error-Code-Mapper-ver1\debug-980007.log",
                    "a",
                    encoding="utf-8",
                ) as _f:
                    _f.write(
                        _json.dumps(
                            {
                                "sessionId": "980007",
                                "hypothesisId": "D",
                                "location": "server.py:post_confirmed_resolution",
                                "message": msg,
                                "data": data,
                                "timestamp": int(_time.time() * 1000),
                            }
                        )
                        + "\n"
                    )
            except OSError:
                pass

        _dbg("entry", {"index": index, "source": body.source})
        # #endregion
        target = _resolve_out_dir(out_dir)
        frame = _load_frame(target)
        row = _row_to_dict(_require_finding(frame, index))
        error_code = str(row.get("error_code") or "").strip()
        if not error_code:
            raise HTTPException(status_code=400, detail="Finding has no error code")
        try:
            result = set_confirmed_resolution(
                error_code,
                body.selected_text,
                body.comment,
                body.source,
            )
            # #region agent log
            _dbg("saved", {"error_code": error_code})
            # #endregion
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/ingest/status")
    def get_ingest_status(out_dir: str | None = None) -> dict[str, Any]:
        target = _resolve_out_dir(out_dir)
        return ingest_status(target)

    @app.get("/api/ui-info")
    def get_ui_info() -> dict[str, Any]:
        """Diagnostics for which SPA bundle the API serves (port 8000)."""
        import cobol_error_scanner.api.server as server_module

        index_path = WEB_DIST / "index.html"
        bundle_name = ""
        has_new_ops_ui = False
        has_confirm_api = False
        if index_path.is_file():
            html = index_path.read_text(encoding="utf-8")
            for part in html.split('"'):
                if part.startswith("/assets/index-") and part.endswith(".js"):
                    bundle_name = part.split("/")[-1]
                    break
            js_path = WEB_DIST / "assets" / bundle_name if bundle_name else None
            if js_path and js_path.is_file():
                body = js_path.read_text(encoding="utf-8", errors="ignore")
                has_new_ops_ui = "Historical Resolution" in body and "Evidence:" not in body
                has_confirm_api = "confirmed-resolution" in body
        for route in app.routes:
            path = getattr(route, "path", "")
            if path == "/api/findings/{index}/confirmed-resolution":
                has_confirm_api = True
                break
        return {
            "web_dist": str(WEB_DIST),
            "web_dist_exists": WEB_DIST.is_dir(),
            "index_html": str(index_path),
            "bundle": bundle_name,
            "has_historical_technical_ops_ui": has_new_ops_ui,
            "has_confirmed_resolution_api": has_confirm_api,
            "server_module": str(Path(server_module.__file__).resolve()),
        }

    @app.post("/api/ingest", response_model=IngestResponse)
    def post_ingest(body: IngestRequest) -> IngestResponse:
        out_path = Path(body.out_dir)
        _set_out_dir(out_path)
        try:
            result = run_ingest(
                Path(body.docs_root),
                out_path,
                rules_path=optional_path(body.rules_path),
                resolver=body.resolver,
                error_code=body.error_code,
                error_field=body.error_field,
                redact=body.redact,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return IngestResponse(**result)

    @app.post("/api/scan", response_model=ScanResponse)
    def post_scan(body: ScanRequest) -> ScanResponse:
        out_path = Path(body.out_dir)
        _set_out_dir(out_path)
        try:
            program_count, finding_count, table_name = run_scan(
                Path(body.source_root),
                Path(body.rules_path),
                out_path,
                body.summarizer,
                error_code=body.error_code,
                error_field=body.error_field,
                corora_mappings=optional_path(body.corora_mappings),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return ScanResponse(
            program_count=program_count,
            finding_count=finding_count,
            table_name=table_name,
        )

    @app.post("/api/v1/lookup", response_model=LookupResponse)
    def post_lookup(
        body: LookupRequest,
        _auth: None = Depends(verify_external_api_keys),
    ) -> LookupResponse:
        try:
            payload = build_lookup_response(
                error_code=body.error_code,
                error_field=body.error_field,
                source_root=body.source_root,
                rules_path=body.rules_path,
                out_dir=body.out_dir,
                corora_mappings=body.corora_mappings,
                summarizer=body.summarizer,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return LookupResponse(**payload)

    @app.get("/api/export/csv")
    def export_csv(
        q: str = "",
        programs: list[str] = Query(default=[]),
        error_codes: str = "",
        field_contains: str = "",
        tab: TabFilter = "all",
        indices: list[int] = Query(default=[]),
        out_dir: str | None = None,
    ) -> Response:
        target = _resolve_out_dir(out_dir)
        frame = _load_frame(target)
        codes, invalid = parse_error_code_tokens(error_codes)
        if invalid:
            raise HTTPException(status_code=400, detail="Invalid error codes")
        filtered = _filter_findings(
            frame,
            programs=programs or None,
            error_codes=codes or None,
            query=q,
            field_contains=field_contains,
            tab=tab,
        )
        if indices:
            valid = [i for i in indices if i in filtered.index]
            subset = filtered.loc[valid]
        else:
            subset = filtered
        return Response(
            content=build_csv_bytes(subset),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="cobol_error_findings.csv"'},
        )

    @app.api_route(
        "/api/{rest:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        include_in_schema=False,
    )
    def unknown_api_route(rest: str) -> None:
        raise HTTPException(status_code=404, detail=f"Unknown API route: /api/{rest}")

    if WEB_DIST.is_dir():

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str) -> FileResponse:
            """Serve built React UI without intercepting /api (StaticFiles mount at / breaks API)."""
            if full_path.startswith("api") or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Unknown API route")
            candidate = WEB_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html", headers=_NO_CACHE_HEADERS)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    host = os.environ.get("COBOL_API_HOST", "127.0.0.1")
    port = int(os.environ.get("COBOL_API_PORT", "8000"))
    print(f"COBOL dashboard API: http://{host}:{port}")
    print(f"  Serving UI from: {WEB_DIST.resolve()}")
    if not WEB_DIST.is_dir():
        print("  WARNING: web/dist missing — run: cd web && npm run build")
    else:
        info_path = WEB_DIST / "index.html"
        if info_path.is_file():
            print(f"  UI index: {info_path}")
    uvicorn.run("cobol_error_scanner.api.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
