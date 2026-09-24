import { useCallback, useEffect, useState } from "react";
import { getFindingJira } from "../api/client";
import type { JiraIssue, JiraSearchResponse } from "../types/jira";

interface JiraInsightsProps {
  index: number;
  outDir?: string;
}

function statusClass(category: string): string {
  if (category === "done") return "jira-status-done";
  if (category === "indeterminate") return "jira-status-progress";
  return "jira-status-todo";
}

function formatUpdated(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function JiraTicketCard({ issue }: { issue: JiraIssue }) {
  return (
    <article className="jira-ticket">
      <div className="jira-ticket-header">
        <div className="jira-ticket-title">
          {issue.url ? (
            <a href={issue.url} target="_blank" rel="noopener noreferrer" className="jira-key">
              {issue.key}
            </a>
          ) : (
            <span className="jira-key">{issue.key}</span>
          )}
          <span className="jira-summary">{issue.summary}</span>
        </div>
        <span className={`jira-status-pill ${statusClass(issue.status_category)}`}>
          {issue.status || "Unknown"}
        </span>
      </div>

      <div className="jira-ticket-meta">
        {issue.issue_type && <span className="jira-meta-chip">{issue.issue_type}</span>}
        {issue.priority && <span className="jira-meta-chip">{issue.priority}</span>}
        {issue.resolution && (
          <span className="jira-meta-chip jira-meta-resolved">{issue.resolution}</span>
        )}
        {issue.assignee && <span className="jira-meta-chip">👤 {issue.assignee}</span>}
        {issue.updated && (
          <span className="jira-meta-chip">Updated {formatUpdated(issue.updated)}</span>
        )}
        {issue.comment_count > 0 && (
          <span className="jira-meta-chip">
            {issue.comment_count} comment{issue.comment_count === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {issue.resolution_excerpt && (
        <div className="jira-resolution-excerpt">
          <span className="jira-excerpt-label">Resolution insight</span>
          <p>{issue.resolution_excerpt}</p>
        </div>
      )}
    </article>
  );
}

export function JiraInsights({ index, outDir }: JiraInsightsProps) {
  const [data, setData] = useState<JiraSearchResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getFindingJira(index, outDir);
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reach the Jira endpoint");
    } finally {
      setLoading(false);
    }
  }, [index, outDir]);

  useEffect(() => {
    let cancelled = false;
    load().catch(() => {
      /* handled in load */
    });
    return () => {
      cancelled = true;
      void cancelled;
    };
  }, [load]);

  const query = data?.query;
  const searchTerms = query?.terms?.length
    ? query.terms
    : query
      ? [query.error_code, query.error_field].filter(Boolean)
      : [];
  const terms = searchTerms.join(", ");

  return (
    <section className="jira-panel">
      <div className="jira-panel-header">
        <div className="jira-panel-heading">
          <span className="jira-panel-logo" aria-hidden="true">
            Jira
          </span>
          <div>
            <h3>Jira Cloud tickets</h3>
            {terms && <p className="jira-panel-subtitle">Searching by {terms}</p>}
          </div>
        </div>
        <button
          type="button"
          className="jira-refresh-btn"
          onClick={() => void load()}
          disabled={loading}
        >
          {loading ? <span className="spinner" /> : "↻"} Search Jira
        </button>
      </div>

      {loading && (
        <div className="jira-loading">
          <span className="spinner" /> Searching Jira…
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
            <strong>Jira Cloud is not connected yet.</strong> Set these environment variables on the
            API server, then reopen this finding:
          </p>
          <ul className="jira-env-list">
            <li>
              <code>JIRA_BASE_URL</code> — e.g. <code>https://your-org.atlassian.net</code>
            </li>
            <li>
              <code>JIRA_EMAIL</code> — your Atlassian account email
            </li>
            <li>
              <code>JIRA_API_TOKEN</code> — an Atlassian API token
            </li>
          </ul>
          <p className="jira-hint-note">
            Optional: <code>JIRA_PROJECTS</code> to scope the search, or <code>JIRA_MOCK=1</code> to
            preview with sample tickets.
          </p>
        </div>
      )}

      {!loading && !error && data && data.configured && data.reachable === false && (
        <div className="alert alert-error jira-alert">
          {data.error || "Could not reach Jira."}
          <button type="button" className="link-button jira-retry" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}

      {!loading && !error && data && data.configured && data.reachable && (
        <>
          {data.mock && <p className="jira-mock-note">Showing sample tickets (JIRA_MOCK enabled).</p>}
          {data.issue_count === 0 ? (
            <p className="jira-empty">No related Jira tickets found for {terms || "this finding"}.</p>
          ) : (
            <>
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
                {data.issues.map((issue) => (
                  <JiraTicketCard key={issue.key} issue={issue} />
                ))}
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
