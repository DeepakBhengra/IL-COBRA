import { useCallback, useEffect, useState } from "react";
import { getDatadogAnalysis } from "../api/client";
import type { DatadogAnalysisReport } from "../types/datadog";

interface DatadogAnalysisProps {
  index: number;
  outDir?: string;
}

function formatCount(value: number): string {
  return value.toLocaleString();
}

export function DatadogAnalysis({ index, outDir }: DatadogAnalysisProps) {
  const [data, setData] = useState<DatadogAnalysisReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getDatadogAnalysis(index, outDir));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reach Datadog");
    } finally {
      setLoading(false);
    }
  }, [index, outDir]);

  useEffect(() => {
    void load();
  }, [load]);

  const code = data?.error_code || "";
  const summary = data?.summary;

  return (
    <section className="dd-panel">
      <div className="dd-panel-header">
        <div className="dd-panel-heading">
          <span className="dd-panel-logo" aria-hidden="true">
            DD
          </span>
          <div>
            <h3>DataDog Analysis</h3>
            <p className="dd-panel-subtitle">
              OrderCreate v6 and v2 responses, last {data?.window_days ?? 15} days
              {code ? `, error code ${code}` : ""}
            </p>
          </div>
        </div>
        <button type="button" className="dd-refresh-btn" onClick={() => void load()} disabled={loading}>
          {loading ? <span className="spinner" /> : "↻"} Run report
        </button>
      </div>

      <p className="dd-scope">
        Includes a response when the error code is {code || "the finding code"}, or when the request
        status is FAILED and the response flag is {code || "that code"}. Production hosts are
        uschileai1401–1404. Services are OrderCreate_v6* and OrderCreate_v2*.
      </p>

      {loading && (
        <div className="dd-loading">
          <span className="spinner" /> Running the Datadog report…
        </div>
      )}

      {!loading && error && (
        <div className="alert alert-error">
          {error}
          <button type="button" className="link-button" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}

      {!loading && !error && data && !data.configured && (
        <div className="dd-hint">
          <p>
            <strong>Datadog is not connected yet.</strong> Set <code>DD_ACCESS_TOKEN</code> and{" "}
            <code>DD_SITE</code> on the API server, then run the report again.
          </p>
        </div>
      )}

      {!loading && !error && data?.error && data.configured && (
        <div className="alert alert-error">{data.error}</div>
      )}

      {!loading && !error && data && data.configured && !data.error && (
        <>
          <div className="dd-metrics">
            <Metric label="Matching responses" value={data.matched} />
            <Metric label="Production" value={summary?.production ?? 0} />
            <Metric label="Test" value={summary?.test ?? 0} />
            <Metric label="North America" value={summary?.north_america ?? 0} />
            <Metric label="EMEA" value={summary?.emea ?? 0} />
            <Metric label="Other regions" value={summary?.other ?? 0} />
            <Metric label="OrderCreate_v6*" value={summary?.order_create_v6 ?? 0} />
            <Metric label="OrderCreate_v2*" value={summary?.order_create_v2 ?? 0} />
          </div>

          {data.truncated && (
            <p className="dd-note">
              The report stopped after {formatCount(data.scanned)} scanned logs. Counts are a partial
              window.
            </p>
          )}

          {data.groups.length === 0 ? (
            <p className="dd-empty">
              No Order Create v2 or v6 responses in the last {data.window_days} days matched {code}.
            </p>
          ) : (
            <div className="dd-table-wrap">
              <table className="dd-table">
                <thead>
                  <tr>
                    <th>Region</th>
                    <th>Environment</th>
                    <th>Host</th>
                    <th>Service</th>
                    <th>Countries</th>
                    <th>Responses</th>
                  </tr>
                </thead>
                <tbody>
                  {data.groups.map((group) => (
                    <tr key={`${group.region}-${group.environment}-${group.host}-${group.service}`}>
                      <td>{group.region}</td>
                      <td>
                        <span className={`dd-env dd-env-${group.environment.toLowerCase()}`}>
                          {group.environment}
                        </span>
                      </td>
                      <td>{group.host}</td>
                      <td>
                        <div>{group.service}</div>
                        {group.services.length > 0 && (
                          <div className="dd-sub">
                            {group.services.map((item) => `${item.name} (${formatCount(item.count)})`).join(", ")}
                          </div>
                        )}
                      </td>
                      <td>
                        {group.countries.length > 0
                          ? group.countries.map((item) => `${item.code} ${formatCount(item.count)}`).join(", ")
                          : "—"}
                      </td>
                      <td className="dd-count">{formatCount(group.count)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="dd-metric">
      <span className="dd-metric-value">{formatCount(value)}</span>
      <span className="dd-metric-label">{label}</span>
    </div>
  );
}
