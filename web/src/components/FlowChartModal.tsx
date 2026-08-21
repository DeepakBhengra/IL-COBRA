import { useEffect } from "react";

import { createPortal } from "react-dom";

import { MermaidFlowChart } from "./MermaidFlowChart";

interface FlowChartModalProps {
  chart: string;
  renderKey: string | number;
  title?: string;
  onClose: () => void;
}

export function FlowChartModal({ chart, renderKey, title, onClose }: FlowChartModalProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div
      className="flowchart-modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Enlarged control flow chart"
      onClick={onClose}
    >
      <div className="flowchart-modal" onClick={(e) => e.stopPropagation()}>
        <div className="flowchart-modal-header">
          <h3>Control Flow Chart{title ? ` — ${title}` : ""}</h3>
          <button
            type="button"
            className="drawer-close"
            onClick={onClose}
            aria-label="Close enlarged view"
          >
            ×
          </button>
        </div>
        <div className="flowchart-modal-body">
          <MermaidFlowChart
            chart={chart}
            renderKey={`modal-${renderKey}`}
            variant="fullscreen"
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}
