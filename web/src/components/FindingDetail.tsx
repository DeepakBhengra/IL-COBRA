import { useEffect, useMemo, useState } from "react";

import { getFinding, getFlowchart } from "../api/client";
import type { FindingRow } from "../types/findings";
import { MermaidFlowChart } from "./MermaidFlowChart";
import { FlowChartModal } from "./FlowChartModal";
import { OperationalDocsPanel } from "./OperationalDocsPanel";

type DetailTab = "details" | "logic" | "flow" | "operational-docs";

type IconName =
  | "code"
  | "tag"
  | "file"
  | "hash"
  | "layers"
  | "flow"
  | "book"
  | "info"
  | "alert"
  | "map"
  | "copy"
  | "check";

const ICON_PATHS: Record<IconName, string> = {
  code: "M8 6l-5 6 5 6M16 6l5 6-5 6",
  tag: "M20.6 13.4 12 22l-9-9V4h9zM7.5 7.5h.01",
  file: "M14 3v5h5M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z",
  hash: "M4 9h16M4 15h16M10 3 8 21M16 3l-2 18",
  layers: "M12 2 2 7l10 5 10-5zM2 12l10 5 10-5M2 17l10 5 10-5",
  flow: "M4 4h6v6H4zM14 14h6v6h-6zM10 7h4a2 2 0 0 1 2 2v5",
  book: "M4 5a2 2 0 0 1 2-2h14v16H6a2 2 0 0 0-2 2zM8 3v14",
  info: "M12 16v-4M12 8h.01M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z",
  alert: "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  map: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14",
  copy: "M9 9h10v10H9zM5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1",
  check: "M20 6 9 17l-5-5",
};

function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
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

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

interface FindingDetailProps {
  index: number | null;
  outDir?: string;
  onClose: () => void;
  onConfigureIngest?: () => void;
}

interface FieldSpec {
  label: string;
  value: string;
  icon?: IconName;
}

export function FindingDetail({ index, outDir, onClose, onConfigureIngest }: FindingDetailProps) {
  const [row, setRow] = useState<FindingRow | null>(null);
  const [chart, setChart] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>("details");
  const [chartExpanded, setChartExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setChartExpanded(false);
    setCopied(false);
  }, [index]);

  useEffect(() => {
    if (index === null) {
      setRow(null);
      setChart("");
      setActiveTab("details");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setActiveTab("details");
    Promise.all([getFinding(index, outDir), getFlowchart(index, outDir)])
      .then(([finding, flow]) => {
        if (!cancelled) {
          setRow(finding);
          setChart(flow.chart);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [index, outDir]);

  const headlineFields = useMemo<FieldSpec[]>(() => {
    if (!row) return [];
    return (
      [
        { label: "Error Code", value: formatValue(row.error_code) },
        { label: "Error Field", value: formatValue(row.error_field) },
        { label: "Program", value: formatValue(row.program) },
        { label: "Line", value: formatValue(row.line) },
        { label: "Paragraph", value: formatValue(row.paragraph) },
      ] as FieldSpec[]
    ).filter((f) => f.value);
  }, [row]);

  const quickFields = useMemo<FieldSpec[]>(() => {
    if (!row) return [];
    return (
      [
        { label: "Error Code", value: formatValue(row.error_code), icon: "tag" },
        { label: "Error Field", value: formatValue(row.error_field), icon: "code" },
        { label: "Program", value: formatValue(row.program), icon: "file" },
        { label: "Line", value: formatValue(row.line), icon: "hash" },
        { label: "Paragraph", value: formatValue(row.paragraph), icon: "layers" },
        { label: "Section", value: formatValue(row.section), icon: "layers" },
        { label: "File", value: formatValue(row.file), icon: "file" },
        { label: "Error Message", value: formatValue(row.error_message), icon: "alert" },
      ] as FieldSpec[]
    ).filter((f) => f.value);
  }, [row]);

  const findingInfo = useMemo<FieldSpec[]>(() => {
    if (!row) return [];
    return (
      [
        { label: "Program", value: formatValue(row.program) },
        { label: "Error Code", value: formatValue(row.error_code) },
        { label: "Error Field", value: formatValue(row.error_field) },
        { label: "File", value: formatValue(row.file) },
        { label: "Line", value: formatValue(row.line) },
        { label: "Paragraph", value: formatValue(row.paragraph) },
        { label: "Section", value: formatValue(row.section) },
      ] as FieldSpec[]
    ).filter((f) => f.value);
  }, [row]);

  const summaryInfo = useMemo<FieldSpec[]>(() => {
    if (!row) return [];
    return (
      [
        { label: "Summary", value: formatValue(row.row_summary) },
        { label: "Mapping Detail", value: formatValue(row.mapping_detail) },
        { label: "Error Message", value: formatValue(row.error_message) },
        { label: "Program Summary", value: formatValue(row.program_summary) },
      ] as FieldSpec[]
    ).filter((f) => f.value);
  }, [row]);

  const logicBlocks = useMemo<FieldSpec[]>(() => {
    if (!row) return [];
    return (
      [
        { label: "Condition", value: formatValue(row.condition) },
        { label: "Parameters", value: formatValue(row.parameters) },
        { label: "Statement", value: formatValue(row.statement) },
        { label: "Logic Context", value: formatValue(row.logic_context) },
      ] as FieldSpec[]
    ).filter((f) => f.value);
  }, [row]);

  if (index === null) return null;

  const copyId = () => {
    if (!row) return;
    const id = [row.program, row.error_code, row.line ? `line ${row.line}` : ""]
      .filter(Boolean)
      .join(" · ");
    navigator.clipboard?.writeText(id).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      },
      () => {
        /* clipboard unavailable */
      },
    );
  };

  const tabs: Array<{ id: DetailTab; label: string; icon: IconName; show: boolean }> = [
    { id: "details", label: "Details", icon: "info", show: true },
    { id: "logic", label: "Condition & Logic", icon: "code", show: logicBlocks.length > 0 },
    { id: "flow", label: "Control Flow", icon: "flow", show: true },
    { id: "operational-docs", label: "Operational Docs", icon: "book", show: true },
  ];

  return (
    <>
      <div className="detail-overlay" role="dialog" aria-label="Finding details">
        <div className="detail-page">
          <div className="detail-page-header">
            <div>
              <div className="detail-eyebrow">Selected Finding Details</div>
              <h1 className="detail-title">Finding Details</h1>
              <p className="detail-subtitle">
                Detailed information for the selected COBOL error finding
              </p>
            </div>
            <button type="button" className="detail-close-tab" onClick={onClose}>
              ← Close Tab
            </button>
          </div>

          {error && <div className="alert alert-error">{error}</div>}

          {loading && (
            <div className="loading-overlay">
              <span className="spinner" /> Loading…
            </div>
          )}

          {row && !loading && !error && (
            <>
              <div className="summary-card">
                <div className="summary-card-icon">
                  <Icon name="alert" />
                </div>
                <div className="summary-fields">
                  {headlineFields.map((f) => (
                    <div key={f.label} className="summary-field">
                      <span className="k">{f.label}</span>
                      <span className="v">{f.value}</span>
                    </div>
                  ))}
                </div>
                <button type="button" className="copy-btn" onClick={copyId}>
                  <Icon name={copied ? "check" : "copy"} />
                  {copied ? "Copied" : "Copy Finding ID"}
                </button>
              </div>

              {quickFields.length > 0 && (
                <div className="info-card-grid">
                  {quickFields.map((f) => (
                    <div key={f.label} className="info-card">
                      <div className="info-card-icon">
                        <Icon name={f.icon ?? "info"} />
                      </div>
                      <div className="info-card-text">
                        <span className="k">{f.label}</span>
                        <span className="v" title={f.value}>
                          {f.value}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className="detail-tabs" role="tablist">
                {tabs
                  .filter((t) => t.show)
                  .map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      role="tab"
                      aria-selected={activeTab === t.id}
                      className={`detail-tab${activeTab === t.id ? " active" : ""}`}
                      onClick={() => setActiveTab(t.id)}
                    >
                      <Icon name={t.icon} />
                      {t.label}
                    </button>
                  ))}
              </div>

              {activeTab === "details" && (
                <div className="section-grid">
                  <SectionCard icon="info" title="Finding Information" fields={findingInfo} />
                  {summaryInfo.length > 0 && (
                    <SectionCard
                      icon="map"
                      title="Mapping & Summary"
                      fields={summaryInfo}
                      wide
                    />
                  )}
                </div>
              )}

              {activeTab === "logic" && (
                <div className="section-stack">
                  {logicBlocks.map((b) => (
                    <div key={b.label} className="section-card">
                      <div className="section-card-header">
                        <span className="section-card-title">
                          <span className="section-card-icon">
                            <Icon name="code" />
                          </span>
                          {b.label}
                        </span>
                      </div>
                      <div className="section-card-body">
                        <pre className="detail-code">{b.value}</pre>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {activeTab === "flow" && (
                <div className="section-card">
                  <div className="section-card-header">
                    <span className="section-card-title">
                      <span className="section-card-icon">
                        <Icon name="flow" />
                      </span>
                      Control Flow Chart
                    </span>
                    {chart && (
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => setChartExpanded(true)}
                      >
                        ⤢ Enlarge
                      </button>
                    )}
                  </div>
                  <div className="section-card-body">
                    <MermaidFlowChart
                      chart={chart}
                      renderKey={index}
                      active={activeTab === "flow"}
                      onExpand={chart ? () => setChartExpanded(true) : undefined}
                    />
                  </div>
                </div>
              )}

              {activeTab === "operational-docs" && (
                <div className="section-card">
                  <div className="section-card-body">
                    <OperationalDocsPanel
                      index={index}
                      outDir={outDir}
                      onConfigureIngest={onConfigureIngest}
                    />
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {chartExpanded && chart && (
        <FlowChartModal
          chart={chart}
          renderKey={index}
          title={
            row
              ? [row.program, row.error_code, row.line]
                  .filter((v) => v !== null && v !== undefined && v !== "")
                  .join(" — ")
              : undefined
          }
          onClose={() => setChartExpanded(false)}
        />
      )}
    </>
  );
}

function SectionCard({
  icon,
  title,
  fields,
  wide,
}: {
  icon: IconName;
  title: string;
  fields: FieldSpec[];
  wide?: boolean;
}) {
  return (
    <div className={`section-card${wide ? " section-card-wide" : ""}`}>
      <div className="section-card-header">
        <span className="section-card-title">
          <span className="section-card-icon">
            <Icon name={icon} />
          </span>
          {title}
        </span>
        <span className="section-card-count">{fields.length} fields</span>
      </div>
      <div className="section-card-body">
        <dl className="kv-list">
          {fields.map((f) => (
            <div key={f.label} className="kv-row">
              <dt>{f.label}</dt>
              <dd>{f.value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
