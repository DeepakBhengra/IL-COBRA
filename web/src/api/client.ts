import type {
  DefaultConfig,
  FilterState,
  FindingRow,
  FindingsResponse,
  MetricsResponse,
  ScanRequest,
  ScanResponse,
} from "../types/findings";
import type {
  ConfirmedResolution,
  ConfirmedResolutionRequest,
  IngestRequest,
  IngestResponse,
  IngestStatus,
  OperationalDocsResponse,
} from "../types/operationalDocs";

function normalizeOutDir(outDir?: string): string | undefined {
  if (!outDir?.trim()) return undefined;
  return outDir.trim().replace(/\\/g, "/");
}

function buildQuery(params: Record<string, string | number | string[] | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) {
      continue;
    }
    if (Array.isArray(value)) {
      value.forEach((v) => search.append(key, v));
    } else {
      const normalized = key === "out_dir" && typeof value === "string" ? normalizeOutDir(value) : value;
      search.set(key, String(normalized ?? value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export class ApiError extends Error {
  readonly status: number;
  readonly url: string;

  constructor(message: string, status: number, url: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.url = url;
  }
}

function formatApiError(status: number, url: string, detail: string): string {
  if (status === 404 && (detail === "Not Found" || detail.includes("Unknown API route"))) {
    if (url.includes("confirmed-resolution")) {
      return (
        "Confirmed resolution API is missing on the server (stale install). " +
        "Stop the API on port 8000, run: pip install -e . from the project root, " +
        "then start with: py -m cobol_error_scanner.api.server or scripts/start-enterprise-ui.ps1"
      );
    }
    return (
      "Cannot reach the COBOL scanner API. Open http://localhost:8000 after running " +
      "cobol-dashboard-api from the project folder (pip install -e .). " +
      "For development, also run: cd web && npm run dev (port 5173 proxies /api to 8000)."
    );
  }
  if (status === 404 && /finding index|finding not found/i.test(detail)) {
    return detail.includes("Close the detail panel")
      ? detail
      : "This finding index is no longer valid (usually after a new scan). " +
          "Close the panel and click the row again.";
  }
  return detail;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    // #region agent log
    if (url.includes("confirmed-resolution")) {
      fetch("http://127.0.0.1:7458/ingest/379c98ef-1254-4beb-8cf0-a82e60c28273", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "980007" },
        body: JSON.stringify({
          sessionId: "980007",
          hypothesisId: "A",
          location: "client.ts:fetchJson:notOk",
          message: "confirmed-resolution HTTP error",
          data: { status: res.status, url },
          timestamp: Date.now(),
        }),
      }).catch(() => {});
    }
    // #endregion
    const body = await res.text();
    let detail = body;
    try {
      const parsed = JSON.parse(body) as { detail?: unknown };
      detail =
        typeof parsed.detail === "string"
          ? parsed.detail
          : parsed.detail != null
            ? JSON.stringify(parsed.detail)
            : body;
    } catch {
      /* use raw body */
    }
    const message = formatApiError(res.status, url, detail);
    throw new ApiError(message, res.status, url);
  }
  return res.json() as Promise<T>;
}

export function filtersToParams(filters: Partial<FilterState>, outDir?: string) {
  return {
    q: filters.q,
    programs: filters.programs,
    error_codes: filters.errorCodes,
    field_contains: filters.fieldContains,
    tab: filters.tab,
    page: filters.page,
    page_size: filters.pageSize,
    out_dir: outDir,
  };
}

export async function getApiHealth(): Promise<{ status: string }> {
  return fetchJson<{ status: string }>("/api/health");
}

export async function getDefaults(): Promise<DefaultConfig> {
  return fetchJson<DefaultConfig>("/api/config/defaults");
}

export async function getMetrics(
  filters: Partial<FilterState>,
  outDir?: string,
): Promise<MetricsResponse> {
  const qs = buildQuery(filtersToParams(filters, outDir));
  return fetchJson<MetricsResponse>(`/api/metrics${qs}`);
}

export async function getFindings(
  filters: Partial<FilterState>,
  outDir?: string,
): Promise<FindingsResponse> {
  const qs = buildQuery(filtersToParams(filters, outDir));
  return fetchJson<FindingsResponse>(`/api/findings${qs}`);
}

export async function getFinding(index: number, outDir?: string): Promise<FindingRow> {
  const qs = buildQuery({ out_dir: outDir });
  return fetchJson<FindingRow>(`/api/findings/${index}${qs}`);
}

export async function getFlowchart(
  index: number,
  outDir?: string,
): Promise<{ chart: string; title: string }> {
  const qs = buildQuery({ index, out_dir: outDir });
  return fetchJson<{ chart: string; title: string }>(`/api/flowchart${qs}`);
}

export async function getOperationalDocs(
  index: number,
  outDir?: string,
): Promise<OperationalDocsResponse> {
  const qs = buildQuery({ out_dir: outDir });
  return fetchJson<OperationalDocsResponse>(`/api/findings/${index}/operational-docs${qs}`);
}

export async function postConfirmedResolution(
  index: number,
  body: ConfirmedResolutionRequest,
  outDir?: string,
): Promise<ConfirmedResolution> {
  const qs = buildQuery({ out_dir: outDir });
  return fetchJson<ConfirmedResolution>(`/api/findings/${index}/confirmed-resolution${qs}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function getIngestStatus(outDir?: string): Promise<IngestStatus> {
  const qs = buildQuery({ out_dir: outDir });
  return fetchJson<IngestStatus>(`/api/ingest/status${qs}`);
}

export async function runIngest(body: IngestRequest): Promise<IngestResponse> {
  return fetchJson<IngestResponse>("/api/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function runScan(body: ScanRequest): Promise<ScanResponse> {
  return fetchJson<ScanResponse>("/api/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function exportCsvUrl(
  filters: Partial<FilterState>,
  indices: number[],
  outDir?: string,
): string {
  const params = filtersToParams(filters, outDir) as Record<string, string | number | string[]>;
  if (indices.length > 0) {
    params.indices = indices.map(String);
  }
  return `/api/export/csv${buildQuery(params)}`;
}
