import { useCallback, useEffect, useState } from "react";
import { getDatadogPayloads } from "../api/client";
import type { DatadogExchange, DatadogPayloadReport } from "../types/datadog";
import { readSessionCache, writeSessionCache } from "../utils/sessionCache";

const PAYLOAD_CACHE = "datadog-payloads";

function payloadKey(
  index: number,
  outDir: string | undefined,
  errorCode: string,
  errorField: string,
  host?: string,
  service?: string,
): string {
  return `${index}|${outDir ?? ""}|${errorCode}|${errorField}|${host ?? ""}|${service ?? ""}`;
}

interface DatadogPayloadsProps {
  index: number;
  outDir?: string;
  errorCode?: string;
  errorField?: string;
  host?: string;
  service?: string;
}

function formatJson(value: unknown): string {
  if (value === null || value === undefined) return "";
  return JSON.stringify(value, null, 2);
}

function ExchangeCard({ item }: { item: DatadogExchange }) {
  const requestText = formatJson(item.request);
  const responseText = formatJson(item.response);
  return (
    <article className="dd-exchange">
      <header className="dd-exchange-meta">
        <span className={`dd-env dd-env-${item.environment.toLowerCase()}`}>{item.environment}</span>
        <strong>{item.service}</strong>
        <span>{item.service_name}</span>
        <span>{item.host}</span>
        {item.country && <span>{item.country}</span>}
        {item.region && <span>{item.region}</span>}
        {item.correlation_id && (
          <span className="dd-correlation">Correlation {item.correlation_id}</span>
        )}
        {item.customer_po && <span>Customer PO {item.customer_po}</span>}
      </header>
      <div className="dd-exchange-grid">
        <div>
          <h4>Request</h4>
          {requestText ? (
            <pre className="dd-json">{requestText}</pre>
          ) : (
            <p className="dd-empty">
              {item.customer_po
                ? `No Order Create request log contained customer PO ${item.customer_po}.`
                : "No request log was found for this correlation id."}
            </p>
          )}
        </div>
        <div>
          <h4>Response</h4>
          {responseText ? (
            <pre className="dd-json">{responseText}</pre>
          ) : (
            <p className="dd-empty">This failure log did not include a response document.</p>
          )}
        </div>
      </div>
    </article>
  );
}

export function DatadogPayloads({
  index,
  outDir,
  errorCode = "",
  errorField = "",
  host,
  service,
}: DatadogPayloadsProps) {
  const cacheKey = payloadKey(index, outDir, errorCode, errorField, host, service);
  const cached = readSessionCache<DatadogPayloadReport>(PAYLOAD_CACHE, cacheKey);
  const [data, setData] = useState<DatadogPayloadReport | null>(cached ?? null);
  const [loading, setLoading] = useState(!cached);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (force = false) => {
      if (!force) {
        const stored = readSessionCache<DatadogPayloadReport>(PAYLOAD_CACHE, cacheKey);
        if (stored) {
          setData(stored);
          setError(null);
          setLoading(false);
          return;
        }
      }
      setData(null);
      setLoading(true);
      setError(null);
      try {
        const report = await getDatadogPayloads(index, outDir, { host, service });
        writeSessionCache(PAYLOAD_CACHE, cacheKey, report);
        setData(report);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to reach Datadog");
      } finally {
        setLoading(false);
      }
    },
    [cacheKey, index, outDir, host, service],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  const code = data?.error_code || "";

  return (
    <section className="dd-panel">
      <div className="dd-panel-header">
        <div className="dd-panel-heading">
          <span className="dd-panel-logo" aria-hidden="true">
            DD
          </span>
          <div>
            <h3>Request / Response</h3>
            <p className="dd-panel-subtitle">
              {service || "OrderCreate v6 and v2"}
              {host ? ` on ${host}` : ""}
              {code ? `, error code ${code}` : ""}, last {data?.window_days ?? 15} days
            </p>
          </div>
        </div>
        <button type="button" className="dd-refresh-btn" onClick={() => void load(true)} disabled={loading}>
          {loading ? <span className="spinner" /> : "↻"} Load payloads
        </button>
      </div>

      <p className="dd-scope">
        The Datadog connection is checked first. For each service that logged a failure, the response
        JSON is shown with the request JSON that shares its correlation id.
      </p>

      {loading && (
        <div className="dd-loading">
          <span className="spinner" /> Checking Datadog and loading payloads…
        </div>
      )}

      {!loading && error && (
        <div className="alert alert-error">
          {error}
          <button type="button" className="link-button" onClick={() => void load(true)}>
            Retry
          </button>
        </div>
      )}

      {!loading && !error && data && !data.configured && (
        <div className="dd-hint">
          <p>
            <strong>Datadog is not connected yet.</strong> Set <code>DD_ACCESS_TOKEN</code> and{" "}
            <code>DD_SITE</code> on the API server, then load the payloads again.
          </p>
        </div>
      )}

      {!loading && !error && data?.error && data.configured && !data.connected && (
        <div className="alert alert-error">{data.error}</div>
      )}

      {!loading && !error && data && data.configured && data.connected && (
        <>
          {data.exchanges.length === 0 ? (
            <p className="dd-empty">
              No Order Create v2 or v6 failure payloads matched {code} in the last {data.window_days}{" "}
              days.
            </p>
          ) : (
            <div className="dd-exchange-list">
              {data.exchanges.map((item, index) => (
                <ExchangeCard key={`${item.correlation_id}-${item.host}-${index}`} item={item} />
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
