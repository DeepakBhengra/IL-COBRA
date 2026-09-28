import { Fragment, useCallback, useEffect, useState, type ReactNode } from "react";
import { getFindingDatadog } from "../api/client";
import type { DatadogLog, DatadogSearchResponse } from "../types/datadog";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlightTerms(text: string, terms: string[]): ReactNode {
  const cleaned = terms.filter((term) => term && term.trim());
  if (!text || cleaned.length === 0) return text;
  const ordered = [...cleaned].sort((a, b) => b.length - a.length);
  const pattern = new RegExp(`(${ordered.map(escapeRegExp).join("|")})`, "gi");
  const parts = text.split(pattern);
  const termSet = new Set(cleaned.map((term) => term.toLowerCase()));
  return parts.map((part, i) =>
    part && termSet.has(part.toLowerCase()) ? (
      <mark key={i} className="jira-mark">
        {part}
      </mark>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  );
}

interface DatadogInsightsProps {
  index: number;
  outDir?: string;
}

function statusClass(group: string): string {
  if (group === "error") return "datadog-status-error";
  if (group === "warn") return "datadog-status-warn";
  return "datadog-status-info";
}

function formatTimestamp(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function LogCard({ log, terms }: { log: DatadogLog; terms: string[] }) {
  return (
    <article className="jira-ticket">
      <div className="jira-ticket-header">
        <div className="jira-ticket-title">
          {log.url ? (
            <a href={log.url} target="_blank" rel="noopener noreferrer" className="jira-key">
              {log.service || "log"}
            </a>
          ) : (
            <span className="jira-key">{log.service || "log"}</span>
          )}
          {log.host && <span className="jira-summary">{log.host}</span>}
        </div>
        <span className={`jira-status-pill ${statusClass(log.status_group)}`}>
          {log.status || log.status_group || "log"}
        </span>
      </div>
      <div className="jira-ticket-meta">
        {log.timestamp && <span className="jira-meta-chip">{formatTimestamp(log.timestamp)}</span>}
        {log.tags.slice(0, 4).map((tag) => (
          <span key={tag} className="jira-meta-chip">
            {tag}
          </span>
        ))}
      </div>
      {log.message && (
        <div className="jira-resolution-excerpt">
          <span className="jira-excerpt-label">Log message</span>
          <p>{highlightTerms(log.message, terms)}</p>
        </div>
      )}
    </article>
  );
}

export function DatadogInsights({ index, outDir }: DatadogInsightsProps) {
  const [data, setData] = useState<DatadogSearchResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getFindingDatadog(index, outDir));
    } catch (err) {
      setData(null);
      setError(err instanceof Error ? err.message : "Datadog search failed");
    } finally {
      setLoading(false);
    }
  }, [index, outDir]);

  useEffect(() => {
    void load();
  }, [load]);

  const query = data?.query;
  const searchTerms = query?.terms?.length
    ? query.terms
    : query
      ? [query.error_code, query.error_field].filter(Boolean)
      : [];
  const terms = searchTerms.join(", ");

  return (
    <section className="jira-panel datadog-panel">
      <div className="jira-panel-header">
        <div className="jira-panel-heading">
          <span className="jira-panel-logo" aria-hidden="true">
            DD
          </span>
          <div>
            <h3>Datadog logs</h3>
            {terms && <p className="jira-panel-subtitle">Searching by {terms}</p>}
          </div>
        </div>
        <button
          type="button"
          className="jira-refresh-btn"
          onClick={() => void load()}
          disabled={loading}
        >
          {loading ? <span className="spinner" /> : "↻"} Search Datadog
        </button>
      </div>

      {loading && (
        <div className="jira-loading">
          <span className="spinner" /> Searching Datadog…
        </div>
      )}

      {!loading && error && (
        <div className="alert alert-error jira-alert">
          {error}
          <button type="button" className="link-button jira-retry" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}

      {!loading && !error && data && !data.configured && (
        <div className="jira-hint">
          <p>
            <strong>Datadog is not connected yet.</strong> Set these environment variables on the
            API server, then reopen this finding:
          </p>
          <ul className="jira-env-list">
            <li>
              <code>DATADOG_API_KEY</code> — Datadog API key
            </li>
            <li>
              <code>DATADOG_APP_KEY</code> — Datadog application key
            </li>
            <li>
              <code>DATADOG_SITE</code> — optional, e.g. <code>datadoghq.com</code> or{" "}
              <code>datadoghq.eu</code>
            </li>
          </ul>
          <p className="jira-hint-note">
            Optional: <code>DATADOG_EXTRA_QUERY</code> to scope the search (for example{" "}
            <code>env:prod</code>), or <code>DATADOG_MOCK=1</code> to preview with sample logs.
          </p>
        </div>
      )}

      {!loading && !error && data && data.configured && data.reachable === false && (
        <div className="alert alert-error jira-alert">
          {data.error || "Could not reach Datadog."}
          <button type="button" className="link-button jira-retry" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}

      {!loading && !error && data && data.configured && data.reachable && (
        <>
          {data.mock && <p className="jira-mock-note">Showing sample logs (DATADOG_MOCK enabled).</p>}
          {data.log_count === 0 ? (
            <p className="jira-empty">
              {data.total_matched && data.total_matched > 0
                ? `Datadog returned ${data.total_matched} log(s), but none literally mention ${terms || "this finding"}.`
                : `No related Datadog logs found for ${terms || "this finding"}.`}
            </p>
          ) : (
            <>
              {data.filtered_out && data.filtered_out > 0 ? (
                <p className="jira-filter-note">
                  Showing {data.log_count} log(s) that mention {terms}; hid {data.filtered_out}{" "}
                  loose match(es) without a literal mention.
                </p>
              ) : null}
              {data.summary && (
                <div className="jira-summary-card">
                  <p className="jira-summary-text">{data.summary}</p>
                  {data.insights.length > 0 && (
                    <ul className="jira-insights-list">
                      {data.insights.map((line, i) => (
                        <li key={i}>{line}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              <div className="jira-ticket-list">
                {data.logs.map((log) => (
                  <LogCard key={log.id || log.message} log={log} terms={searchTerms} />
                ))}
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
