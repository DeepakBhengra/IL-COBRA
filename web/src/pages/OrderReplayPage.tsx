import { useMemo, useState } from "react";

type ReplayTab = "all" | "success" | "failed";

type CurlKind = "create" | "modify";

type ReplayStatus = "ready" | "success" | "failed";

interface ReplayRun {
  id: string;
  orderNumber: string;
  kinds: CurlKind[];
  status: ReplayStatus;
  curl: string;
  source: string;
  createdAt: number;
}

type IconName =
  | "runs"
  | "success"
  | "failed"
  | "cart"
  | "search"
  | "refresh"
  | "calendar"
  | "copy"
  | "check"
  | "send";

const ICON_PATHS: Record<IconName, string> = {
  runs: "M8 6h11M8 12h11M8 18h11M3 6h.01M3 12h.01M3 18h.01",
  success: "M20 6 9 17l-5-5",
  failed: "M18 6 6 18M6 6l12 12",
  cart: "M6 6h15l-1.5 9h-12zM6 6 5 3H2M9 20h.01M18 20h.01",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  refresh: "M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5",
  calendar: "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
  copy: "M9 9h10v10H9zM5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1",
  check: "M20 6 9 17l-5-5",
  send: "M22 2 11 13M22 2l-7 20-4-9-9-4z",
};

function Icon({ name, size = 16, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}

function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

function formatRangeLabel(fromIso: string, toIso: string): string {
  const opts: Intl.DateTimeFormatOptions = {
    month: "2-digit",
    day: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  };
  const from = new Date(fromIso);
  const to = new Date(toIso);
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return "Select a date range";
  return `${from.toLocaleString(undefined, opts)} – ${to.toLocaleString(undefined, opts)}`;
}

/**
 * Build a representative curl for the given order number and curl kind.
 *
 * The Datadog log search and Ingram order APIs are not available in this
 * environment, so the request is constructed client-side from a template with
 * placeholder host/token values (never real credentials). This lets an operator
 * preview and edit the request before wiring it to a backend.
 */
function buildCurl(orderNumber: string, kind: CurlKind): string {
  const path = kind === "create" ? "orders/v6/create" : "orders/v6/modify";
  const op = kind === "create" ? "OrderCreate" : "OrderModify";
  const body =
    kind === "create"
      ? `{\n    "customerOrderNumber": "${orderNumber}",\n    "operation": "OrderCreate",\n    "convertedFrom": "v2"\n  }`
      : `{\n    "customerOrderNumber": "${orderNumber}",\n    "operation": "OrderModify"\n  }`;
  return [
    `curl -X POST "https://\${ORDER_API_HOST}/${path}" \\`,
    `  -H "Authorization: Bearer \${ORDER_API_TOKEN}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -H "X-Operation: ${op}" \\`,
    `  -d '${body}'`,
  ].join("\n");
}

function makeRun(orderNumber: string, kinds: CurlKind[]): ReplayRun {
  const curl = kinds.map((k) => buildCurl(orderNumber, k)).join("\n\n");
  const source = kinds.includes("create") ? "converted from v2" : "prepared from request";
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    orderNumber,
    kinds,
    status: "ready",
    curl,
    source,
    createdAt: Date.now(),
  };
}

const TABS: Array<{ id: ReplayTab; label: string }> = [
  { id: "all", label: "All Results" },
  { id: "success", label: "Success" },
  { id: "failed", label: "Failed" },
];

const KIND_LABEL: Record<CurlKind, string> = {
  create: "Order Create",
  modify: "Order Modify",
};

export function OrderReplayPage() {
  const now = useMemo(() => new Date(), []);
  const monthAgo = useMemo(() => new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000), [now]);

  const [orderNumber, setOrderNumber] = useState("");
  const [buildCreate, setBuildCreate] = useState(true);
  const [buildModify, setBuildModify] = useState(false);
  const [fromDate, setFromDate] = useState(toLocalInputValue(monthAgo));
  const [toDate, setToDate] = useState(toLocalInputValue(now));
  const [runs, setRuns] = useState<ReplayRun[]>([]);
  const [tab, setTab] = useState<ReplayTab>("all");
  const [banner, setBanner] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const metrics = useMemo(() => {
    const success = runs.filter((r) => r.status === "success").length;
    const failed = runs.filter((r) => r.status === "failed").length;
    return { runs: runs.length, success, failed };
  }, [runs]);

  const tabCounts = useMemo(
    () => ({
      all: runs.length,
      success: runs.filter((r) => r.status === "success").length,
      failed: runs.filter((r) => r.status === "failed").length,
    }),
    [runs],
  );

  const visibleRuns = useMemo(() => {
    const ordered = [...runs].sort((a, b) => b.createdAt - a.createdAt);
    if (tab === "success") return ordered.filter((r) => r.status === "success");
    if (tab === "failed") return ordered.filter((r) => r.status === "failed");
    return ordered;
  }, [runs, tab]);

  const selectedKinds = (): CurlKind[] => {
    const kinds: CurlKind[] = [];
    if (buildCreate) kinds.push("create");
    if (buildModify) kinds.push("modify");
    return kinds;
  };

  const handleRun = () => {
    const trimmed = orderNumber.trim();
    if (!trimmed) {
      setError("Enter a customer order number to search.");
      return;
    }
    const kinds = selectedKinds();
    if (kinds.length === 0) {
      setError("Select at least one curl type (Order Create or Order Modify).");
      return;
    }
    setError(null);
    const run = makeRun(trimmed, kinds);
    run.status = "success";
    setRuns((prev) => [run, ...prev]);
    const primaryLabel = kinds.includes("create") ? "Order Create v2" : "Order Modify";
    setBanner(
      `v6 request ready (converted from ${primaryLabel}) for '${trimmed}'. Edit the curl, then Re-Submit. Source: ${run.source}`,
    );
  };

  const handleResubmit = (id: string) => {
    setRuns((prev) =>
      prev.map((r) => (r.id === id ? { ...r, status: "success", createdAt: Date.now() } : r)),
    );
  };

  const handleReset = () => {
    setOrderNumber("");
    setBuildCreate(true);
    setBuildModify(false);
    setBanner(null);
    setError(null);
  };

  const handleCopy = async (run: ReplayRun) => {
    try {
      await navigator.clipboard.writeText(run.curl);
      setCopiedId(run.id);
      window.setTimeout(() => setCopiedId((cur) => (cur === run.id ? null : cur)), 1600);
    } catch {
      setError("Could not copy to clipboard.");
    }
  };

  return (
    <>
      <div className="page-heading">
        <span className="page-eyebrow">Order Replay</span>
        <h1 className="page-title">Order Replay</h1>
        <p className="page-subtitle">
          Search Datadog checkout logs, prepare Order Create and Order Modify curls, and replay
          requests.
        </p>
      </div>

      <div className="replay-metrics">
        <div className="replay-metric">
          <span className="replay-metric-icon">
            <Icon name="runs" size={18} />
          </span>
          <div className="replay-metric-body">
            <div className="replay-metric-label">Runs</div>
            <div className="replay-metric-value">{metrics.runs}</div>
          </div>
        </div>
        <div className="replay-metric">
          <span className="replay-metric-icon is-success">
            <Icon name="success" size={18} />
          </span>
          <div className="replay-metric-body">
            <div className="replay-metric-label">Success</div>
            <div className="replay-metric-value">{metrics.success}</div>
          </div>
        </div>
        <div className="replay-metric">
          <span className="replay-metric-icon is-failed">
            <Icon name="failed" size={18} />
          </span>
          <div className="replay-metric-body">
            <div className="replay-metric-label">Failed</div>
            <div className="replay-metric-value">{metrics.failed}</div>
          </div>
        </div>
        <div className="replay-metric">
          <span className="replay-metric-icon is-muted">
            <Icon name="cart" size={18} />
          </span>
          <div className="replay-metric-body">
            <div className="replay-metric-label">Impulse Order</div>
            <div className="replay-metric-value replay-metric-empty">—</div>
          </div>
        </div>
      </div>

      <div className="replay-tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`replay-tab${tab === t.id ? " active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            <span className="replay-tab-badge">{tabCounts[t.id]}</span>
          </button>
        ))}
      </div>

      <section className="replay-panel">
        <h2 className="replay-panel-title">Search Datadog Logs</h2>
        <p className="replay-panel-subtitle">
          Enter a customer order number and select curl types to build
        </p>

        <div className="replay-kind-row">
          <label className="replay-check">
            <input
              type="checkbox"
              checked={buildCreate}
              onChange={(e) => setBuildCreate(e.target.checked)}
            />
            <span>Order Create curl</span>
          </label>
          <label className="replay-check">
            <input
              type="checkbox"
              checked={buildModify}
              onChange={(e) => setBuildModify(e.target.checked)}
            />
            <span>Order Modify curl</span>
          </label>
        </div>

        <div className="replay-search-row">
          <div className="replay-search-wrap">
            <span className="replay-search-icon" aria-hidden="true">
              <Icon name="search" />
            </span>
            <input
              type="search"
              className="replay-search-input"
              placeholder="Customer order number (e.g. P28062375)"
              value={orderNumber}
              onChange={(e) => setOrderNumber(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleRun();
              }}
            />
          </div>
          <button type="button" className="replay-run-btn" onClick={handleRun}>
            Run
          </button>
          <button type="button" className="replay-icon-btn" title="Reset" onClick={handleReset}>
            <Icon name="refresh" />
          </button>
        </div>

        <div className="replay-daterange">
          <span className="replay-daterange-icon" aria-hidden="true">
            <Icon name="calendar" />
          </span>
          <span className="replay-daterange-label">{formatRangeLabel(fromDate, toDate)}</span>
          <div className="replay-daterange-inputs">
            <input
              type="datetime-local"
              value={fromDate}
              max={toDate}
              onChange={(e) => setFromDate(e.target.value)}
              aria-label="From date"
            />
            <span className="replay-daterange-sep">–</span>
            <input
              type="datetime-local"
              value={toDate}
              min={fromDate}
              onChange={(e) => setToDate(e.target.value)}
              aria-label="To date"
            />
          </div>
        </div>

        {error && <div className="alert alert-error replay-alert">{error}</div>}
        {banner && <div className="replay-banner">{banner}</div>}
      </section>

      <section className="replay-results">
        {visibleRuns.length === 0 ? (
          <div className="replay-empty">
            {runs.length === 0
              ? "No runs yet. Enter a customer order number and click Run to build a request."
              : "No results in this tab."}
          </div>
        ) : (
          visibleRuns.map((run) => (
            <article key={run.id} className="replay-result-card">
              <header className="replay-result-header">
                <div className="replay-result-title">
                  <span className="replay-result-order">{run.orderNumber}</span>
                  <div className="replay-result-kinds">
                    {run.kinds.map((k) => (
                      <span key={k} className="replay-kind-pill">
                        {KIND_LABEL[k]}
                      </span>
                    ))}
                  </div>
                </div>
                <span className={`replay-status replay-status-${run.status}`}>
                  {run.status === "success" ? "Success" : run.status === "failed" ? "Failed" : "Ready"}
                </span>
              </header>
              <pre className="replay-curl">{run.curl}</pre>
              <footer className="replay-result-footer">
                <span className="replay-result-source">Source: {run.source}</span>
                <div className="replay-result-actions">
                  <button
                    type="button"
                    className="replay-ghost-btn"
                    onClick={() => handleCopy(run)}
                  >
                    <Icon name={copiedId === run.id ? "check" : "copy"} size={14} />
                    {copiedId === run.id ? "Copied" : "Copy curl"}
                  </button>
                  <button
                    type="button"
                    className="replay-resubmit-btn"
                    onClick={() => handleResubmit(run.id)}
                  >
                    <Icon name="send" size={14} />
                    Re-Submit
                  </button>
                </div>
              </footer>
            </article>
          ))
        )}
      </section>
    </>
  );
}
