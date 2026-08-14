import { useEffect, useState } from "react";

import { getFinding, getFlowchart } from "../api/client";

import type { FindingRow } from "../types/findings";

import { DETAIL_FIELDS } from "../types/findings";

import { MermaidFlowChart } from "./MermaidFlowChart";

import { OperationalDocsPanel } from "./OperationalDocsPanel";



type DetailTab = "details" | "operational-docs";



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



export function FindingDetail({ index, outDir, onClose, onConfigureIngest }: FindingDetailProps) {

  const [row, setRow] = useState<FindingRow | null>(null);

  const [chart, setChart] = useState<string>("");

  const [loading, setLoading] = useState(false);

  const [error, setError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<DetailTab>("details");



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



  if (index === null) return null;



  return (

    <>

      <div className="drawer-overlay" onClick={onClose} aria-hidden="true" />

      <aside className="drawer wide" role="dialog" aria-label="Finding details">

        <div className="drawer-header">

          <h2>Finding Details</h2>

          <button type="button" className="drawer-close" onClick={onClose} aria-label="Close">

            ×

          </button>

        </div>

        <div className="drawer-tabs" role="tablist">

          <button

            type="button"

            role="tab"

            className={`drawer-tab${activeTab === "details" ? " active" : ""}`}

            aria-selected={activeTab === "details"}

            onClick={() => setActiveTab("details")}

          >

            Details

          </button>

          <button

            type="button"

            role="tab"

            className={`drawer-tab${activeTab === "operational-docs" ? " active" : ""}`}

            aria-selected={activeTab === "operational-docs"}

            onClick={() => setActiveTab("operational-docs")}

          >

            Operational Docs

          </button>

        </div>

        <div className="drawer-body">

          {error && <div className="alert alert-error">{error}</div>}

          {activeTab === "details" && (

            <>

              {loading && (

                <div className="loading-overlay">

                  <span className="spinner" /> Loading…

                </div>

              )}

              {row && !loading && !error && (

                <>

                  <dl>

                    {DETAIL_FIELDS.map(([label, key]) => {

                      const value = formatValue(row[key]);

                      if (!value) return null;

                      return (

                        <div key={key} className="detail-field">

                          <dt>{label}</dt>

                          <dd>{value}</dd>

                        </div>

                      );

                    })}

                    {row.program_summary && (

                      <div className="detail-field">

                        <dt>Program summary</dt>

                        <dd>{row.program_summary}</dd>

                      </div>

                    )}

                  </dl>

                  <div className="detail-field">

                    <dt>Control flow chart</dt>

                    <dd>

                      <MermaidFlowChart
                        chart={chart}
                        renderKey={index}
                        active={activeTab === "details"}
                      />

                    </dd>

                  </div>

                </>

              )}

            </>

          )}

          {activeTab === "operational-docs" && (

            <OperationalDocsPanel

              index={index}

              outDir={outDir}

              onConfigureIngest={onConfigureIngest}

            />

          )}

        </div>

      </aside>

    </>

  );

}

