import { useCallback, useEffect, useState } from "react";
import {
  getApiHealth,
  getIngestStatus,
  getOperationalDocs,
  postConfirmedResolution,
} from "../api/client";
import type {
  ConfirmedResolution,
  ConfirmedResolutionSource,
  IngestStatus,
  OperationalDocumentRow,
  OperationalDocsResponse,
  TechnicalResolution,
} from "../types/operationalDocs";
import { ConfirmResolutionModal } from "./ConfirmResolutionModal";

interface OperationalDocsPanelProps {
  index: number;
  outDir?: string;
  onConfigureIngest?: () => void;
}

type PendingSelection = {
  text: string;
  source: ConfirmedResolutionSource;
};

function insidelineNoOpsDocsMessage(errorCode: string): string {
  const code = errorCode.trim().toUpperCase();
  if (code) {
    return (
      `Please contact Insideline Team with extracted error logs and request curls for analysing error code ${code}.`
    );
  }
  return (
    "Please contact Insideline Team with extracted error logs and request curls for analysing this error code."
  );
}

function errorCodeFromFindingKey(findingKey: string): string {
  return findingKey.split("|")[1]?.trim() || "";
}

function confidenceClass(confidence: string): string {
  if (confidence === "high") return "confidence-high";
  if (confidence === "medium") return "confidence-medium";
  if (confidence === "low") return "confidence-low";
  return "";
}

function docTypeLabel(docType: string): string {
  const labels: Record<string, string> = {
    pdf: "PDF",
    word: "DOCX",
    html: "HTML",
    ticket: "Ticket",
    chat: "Chat",
    email: "Email",
    log: "Log",
    incident: "Incident",
    runbook: "Runbook",
    csv: "CSV",
    excel: "Excel",
    unknown: "Document",
  };
  return labels[docType] ?? docType.toUpperCase();
}

const TECHNICAL_FIELD_LABELS: { key: keyof TechnicalResolution; label: string }[] = [
  { key: "program", label: "Program" },
  { key: "error_code", label: "Error code" },
  { key: "error_field", label: "Error field" },
  { key: "line", label: "Line" },
  { key: "paragraph", label: "Paragraph" },
  { key: "section", label: "Section" },
  { key: "statement", label: "Statement" },
  { key: "row_summary", label: "Summary" },
  { key: "error_message", label: "Error message" },
];

function historicalText(doc: OperationalDocumentRow): string {
  return (doc.historical_resolution || doc.link_evidence || "").trim();
}

function splitConditionTokens(condition: string): string[] {
  return condition
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function truncateLabel(text: string, max = 120): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

function hasTechnicalResolution(tech: TechnicalResolution | undefined): boolean {
  if (!tech) return false;
  if (tech.condition && String(tech.condition).trim()) return true;
  return TECHNICAL_FIELD_LABELS.some(({ key }) => {
    const val = tech[key];
    return val !== undefined && val !== null && String(val).trim() !== "";
  });
}

function isConfirmedSelection(
  confirmed: ConfirmedResolution | undefined,
  text: string,
  source: ConfirmedResolutionSource,
): boolean {
  if (!confirmed?.selected_text) return false;
  return confirmed.source === source && confirmed.selected_text === text;
}

interface DocumentResolutionSectionsProps {
  doc: OperationalDocumentRow;
  confirmed?: ConfirmedResolution;
  onSelect: (selection: PendingSelection) => void;
}

function DocumentResolutionSections({ doc, confirmed, onSelect }: DocumentResolutionSectionsProps) {
  const historical = historicalText(doc);
  const technical = doc.technical_resolution ?? {};
  const conditionRaw = technical.condition ? String(technical.condition).trim() : "";
  const conditionTokens = conditionRaw ? splitConditionTokens(conditionRaw) : [];
  const showTechnical = hasTechnicalResolution(technical);
  const showResolution = Boolean(historical || showTechnical || confirmed?.selected_text);

  if (!showResolution) {
    return null;
  }

  const docId = doc.document_id || "doc";

  return (
    <section className="ops-resolution-block">
      <h5 className="ops-resolution-heading">Resolution</h5>

      {confirmed?.selected_text && (
        <div className="ops-resolution-subsection ops-confirmed-block">
          <h6>Confirmed Resolution</h6>
          <p className="ops-confirmed-selected">
            <span className="ops-confirmed-label">Selected:</span> {confirmed.selected_text}
          </p>
          {confirmed.comment && (
            <p className="ops-confirmed-comment">
              <span className="ops-confirmed-label">Comment:</span> {confirmed.comment}
            </p>
          )}
          <p className="ops-confirmed-meta">
            From {confirmed.source === "historical" ? "Historical Resolution" : "Condition"} ·{" "}
            {confirmed.error_code}
          </p>
        </div>
      )}

      <div className="ops-resolution-subsection">
        <h6>Historical Resolution</h6>
        {historical ? (
          <ul className="ops-selectable-list">
            <li className="ops-radio-row">
              <label>
                <input
                  type="radio"
                  name={`historical-${docId}`}
                  checked={isConfirmedSelection(confirmed, historical, "historical")}
                  onChange={() => onSelect({ text: historical, source: "historical" })}
                />
                <span className="ops-historical-text">{historical}</span>
              </label>
            </li>
          </ul>
        ) : (
          <p className="ops-resolution-empty">No operational excerpt available for this document.</p>
        )}
      </div>

      <div className="ops-resolution-subsection">
        <h6>Technical Resolution</h6>
        {showTechnical ? (
          <dl className="ops-technical-dl">
            {TECHNICAL_FIELD_LABELS.map(({ key, label }) => {
              const val = technical[key];
              if (val === undefined || val === null || String(val).trim() === "") {
                return null;
              }
              return (
                <div key={key} className="ops-technical-row">
                  <dt>{label}</dt>
                  <dd>{String(val)}</dd>
                </div>
              );
            })}
            {conditionTokens.length > 0 && (
              <div className="ops-technical-row ops-condition-row">
                <dt>Condition</dt>
                <dd>
                  {conditionRaw && (
                    <p className="ops-condition-context" title={conditionRaw}>
                      {truncateLabel(conditionRaw, 200)}
                    </p>
                  )}
                  <ul className="ops-selectable-list">
                    {conditionTokens.map((token) => (
                      <li key={token} className="ops-radio-row">
                        <label>
                          <input
                            type="radio"
                            name={`condition-${docId}`}
                            checked={isConfirmedSelection(confirmed, token, "condition")}
                            onChange={() => onSelect({ text: token, source: "condition" })}
                          />
                          <span>{token}</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                </dd>
              </div>
            )}
          </dl>
        ) : (
          <p className="ops-resolution-empty">No COBOL finding details available.</p>
        )}
      </div>
    </section>
  );
}

export function OperationalDocsPanel({
  index,
  outDir,
  onConfigureIngest,
}: OperationalDocsPanelProps) {
  const [data, setData] = useState<OperationalDocsResponse | null>(null);
  const [status, setStatus] = useState<IngestStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingSelection, setPendingSelection] = useState<PendingSelection | null>(null);
  const [saving, setSaving] = useState(false);

  const refreshDocs = useCallback(async () => {
    await getApiHealth();
    const [docs, ingestStatus] = await Promise.all([
      getOperationalDocs(index, outDir),
      getIngestStatus(outDir),
    ]);
    setData(docs);
    setStatus(ingestStatus);
    return docs;
  }, [index, outDir]);

  const loadDocs = useCallback(async () => {
    // #region agent log
    fetch("http://127.0.0.1:7458/ingest/379c98ef-1254-4beb-8cf0-a82e60c28273", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "980007" },
      body: JSON.stringify({
        sessionId: "980007",
        hypothesisId: "C",
        location: "OperationalDocsPanel.tsx:loadDocs:entry",
        message: "loadDocs started",
        data: { index },
        timestamp: Date.now(),
      }),
    }).catch(() => {});
    // #endregion
    setLoading(true);
    setError(null);
    try {
      await refreshDocs();
      // #region agent log
      fetch("http://127.0.0.1:7458/ingest/379c98ef-1254-4beb-8cf0-a82e60c28273", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "980007" },
        body: JSON.stringify({
          sessionId: "980007",
          hypothesisId: "C",
          location: "OperationalDocsPanel.tsx:loadDocs:success",
          message: "loadDocs completed",
          data: {},
          timestamp: Date.now(),
        }),
      }).catch(() => {});
      // #endregion
    } finally {
      setLoading(false);
    }
  }, [refreshDocs]);

  useEffect(() => {
    let cancelled = false;
    loadDocs().catch((err: Error) => {
      if (!cancelled) {
        setError(err.message);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [loadDocs]);

  const handleConfirm = async (comment: string) => {
    // #region agent log
    fetch("http://127.0.0.1:7458/ingest/379c98ef-1254-4beb-8cf0-a82e60c28273", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "980007" },
      body: JSON.stringify({
        sessionId: "980007",
        hypothesisId: "B",
        location: "OperationalDocsPanel.tsx:handleConfirm:entry",
        message: "handleConfirm called",
        data: {
          hasPending: Boolean(pendingSelection),
          index,
          outDir: outDir ?? null,
          source: pendingSelection?.source ?? null,
        },
        timestamp: Date.now(),
      }),
    }).catch(() => {});
    // #endregion
    if (!pendingSelection) return;
    setSaving(true);
    setError(null);
    try {
      await postConfirmedResolution(
        index,
        {
          selected_text: pendingSelection.text,
          comment,
          source: pendingSelection.source,
        },
        outDir,
      );
      // #region agent log
      fetch("http://127.0.0.1:7458/ingest/379c98ef-1254-4beb-8cf0-a82e60c28273", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "980007" },
        body: JSON.stringify({
          sessionId: "980007",
          hypothesisId: "A",
          location: "OperationalDocsPanel.tsx:handleConfirm:postOk",
          message: "postConfirmedResolution succeeded",
          data: {},
          timestamp: Date.now(),
        }),
      }).catch(() => {});
      // #endregion
      setPendingSelection(null);
      await refreshDocs();
      // #region agent log
      fetch("http://127.0.0.1:7458/ingest/379c98ef-1254-4beb-8cf0-a82e60c28273", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "980007" },
        body: JSON.stringify({
          sessionId: "980007",
          hypothesisId: "C",
          location: "OperationalDocsPanel.tsx:handleConfirm:refreshOk",
          message: "refreshDocs after confirm completed",
          data: {},
          timestamp: Date.now(),
        }),
      }).catch(() => {});
      // #endregion
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save confirmed resolution";
      // #region agent log
      fetch("http://127.0.0.1:7458/ingest/379c98ef-1254-4beb-8cf0-a82e60c28273", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "980007" },
        body: JSON.stringify({
          sessionId: "980007",
          hypothesisId: "A",
          location: "OperationalDocsPanel.tsx:handleConfirm:error",
          message: "handleConfirm failed",
          data: { err: message },
          timestamp: Date.now(),
        }),
      }).catch(() => {});
      // #endregion
      setError(message);
      throw err;
    } finally {
      setSaving(false);
    }
  };

  const sourceLabel =
    pendingSelection?.source === "historical" ? "Historical Resolution" : "Condition";

  if (loading) {
    return (
      <div className="loading-overlay">
        <span className="spinner" /> Loading operational documents…
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="ops-empty-state">
        <h3>Could not load operational documents</h3>
        <p className="alert alert-error">{error}</p>
        <p className="ops-status-hint">
          Ensure <code>out/documents.jsonl</code> exists (run ingest from Scan Settings) and the
          output folder matches your scan. After a new scan, close this panel and reopen the
          finding.
        </p>
        {onConfigureIngest && (
          <button type="button" className="secondary-btn" onClick={onConfigureIngest}>
            Configure ingestion
          </button>
        )}
      </div>
    );
  }

  if (!data?.has_artifacts) {
    const confirmed = data?.confirmed_resolution;
    const findingCode =
      errorCodeFromFindingKey(data?.finding_key ?? "") ||
      confirmed?.error_code ||
      "";
    return (
      <>
        <div className="ops-empty-state">
          <h3>No operational documents ingested</h3>
          <p className="ops-insideline-contact">
            {insidelineNoOpsDocsMessage(findingCode)}
          </p>
          <p>
            Ingest supporting documents (PDF, DOCX, Confluence HTML exports, Jira ticket exports,
            chat logs, incidents, etc.) from a server-side folder to see resolution summaries linked
            to this finding.
          </p>
          {confirmed?.selected_text && (
            <div className="ops-confirmed-block ops-confirmed-standalone">
              <h6>Confirmed Resolution</h6>
              <p className="ops-confirmed-selected">
                <span className="ops-confirmed-label">Selected:</span> {confirmed.selected_text}
              </p>
              {confirmed.comment && (
                <p className="ops-confirmed-comment">
                  <span className="ops-confirmed-label">Comment:</span> {confirmed.comment}
                </p>
              )}
            </div>
          )}
          {status && status.has_documents === false && (
            <p className="ops-status-hint">
              Output folder has no <code>documents.jsonl</code> yet.
            </p>
          )}
          {onConfigureIngest && (
            <button type="button" className="secondary-btn" onClick={onConfigureIngest}>
              Configure ingestion
            </button>
          )}
        </div>
        <ConfirmResolutionModal
          open={pendingSelection !== null}
          selectedText={pendingSelection?.text ?? ""}
          sourceLabel={sourceLabel}
          saving={saving}
          onConfirm={handleConfirm}
          onCancel={() => setPendingSelection(null)}
        />
      </>
    );
  }

  if (data.document_count === 0) {
    const findingCode = errorCodeFromFindingKey(data.finding_key) || "—";
    const confirmed = data.confirmed_resolution;
    return (
      <>
        <div className="ops-empty-state">
          <h3>No linked documents for this finding</h3>
          <p className="ops-insideline-contact">
            {insidelineNoOpsDocsMessage(findingCode === "—" ? "" : findingCode)}
          </p>
          <p>
            {status?.document_count ?? 0} document(s) ingested overall, but none match error code{" "}
            <strong>{findingCode}</strong> in the current scan.
          </p>
          {confirmed?.selected_text && (
            <div className="ops-confirmed-block ops-confirmed-standalone">
              <h6>Confirmed Resolution</h6>
              <p className="ops-confirmed-selected">
                <span className="ops-confirmed-label">Selected:</span> {confirmed.selected_text}
              </p>
              {confirmed.comment && (
                <p className="ops-confirmed-comment">
                  <span className="ops-confirmed-label">Comment:</span> {confirmed.comment}
                </p>
              )}
            </div>
          )}
          <p className="ops-status-hint">
            Operational docs are scoped to the error code(s) in your last COBOL scan. If you
            recently changed the focused scan code (e.g. from D6 to SE), run ingestion again from
            Scan Settings. Documents about other codes will not appear for this finding.
          </p>
          {data.last_ingested_at && (
            <p className="ops-status-hint">Last ingested: {data.last_ingested_at}</p>
          )}
          {onConfigureIngest && (
            <button type="button" className="secondary-btn" onClick={onConfigureIngest}>
              Configure ingestion
            </button>
          )}
        </div>
        <ConfirmResolutionModal
          open={pendingSelection !== null}
          selectedText={pendingSelection?.text ?? ""}
          sourceLabel={sourceLabel}
          saving={saving}
          onConfirm={handleConfirm}
          onCancel={() => setPendingSelection(null)}
        />
      </>
    );
  }

  const confirmed = data.confirmed_resolution;

  return (
    <div className="ops-docs-panel">
      {error && <p className="alert alert-error">{error}</p>}

      {(data.summary || data.steps.length > 0) && (
        <section className="resolution-card">
          <div className="resolution-card-header">
            <h3>Resolution summary</h3>
            {data.confidence && (
              <span className={`confidence-badge ${confidenceClass(data.confidence)}`}>
                {data.confidence}
              </span>
            )}
          </div>
          {data.summary && <p className="resolution-summary">{data.summary}</p>}
          {data.steps.length > 0 && (
            <ol className="resolution-steps">
              {data.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          )}
          {data.provider && <p className="ops-provider-hint">Provider: {data.provider}</p>}
        </section>
      )}

      <section className="ops-doc-list">
        <h3>Linked documents ({data.document_count})</h3>
        {data.documents.map((doc) => (
          <article key={doc.document_id} className="ops-doc-card">
            <div className="ops-doc-card-header">
              <span className={`doc-type-pill doc-type-${doc.doc_type}`}>
                {docTypeLabel(doc.doc_type)}
              </span>
              {doc.link_score > 0 && (
                <span className="link-score">Match {Math.round(doc.link_score * 100)}%</span>
              )}
            </div>
            <h4>{doc.title || doc.document_id}</h4>
            {doc.source_path && (
              <p className="ops-doc-path" title={doc.source_path}>
                {doc.source_path}
              </p>
            )}
            {doc.body_preview && <p className="ops-doc-preview">{doc.body_preview.slice(0, 200)}</p>}
            <DocumentResolutionSections
              doc={doc}
              confirmed={confirmed}
              onSelect={setPendingSelection}
            />
          </article>
        ))}
      </section>

      {data.last_ingested_at && (
        <p className="ops-status-hint">Last ingested: {data.last_ingested_at}</p>
      )}

      <ConfirmResolutionModal
        open={pendingSelection !== null}
        selectedText={pendingSelection?.text ?? ""}
        sourceLabel={sourceLabel}
        saving={saving}
        onConfirm={handleConfirm}
        onCancel={() => setPendingSelection(null)}
      />
    </div>
  );
}
