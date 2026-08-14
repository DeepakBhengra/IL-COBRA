import { useCallback, useEffect, useRef, useState } from "react";

import mermaid from "mermaid";

const MIN_SCALE = 0.25;
const MAX_SCALE = 3.5;
const BUTTON_STEP = 0.2;
const WHEEL_STEP = 0.12;

function clampScale(value: number): number {
  return Math.max(MIN_SCALE, Math.min(MAX_SCALE, value));
}

interface MermaidFlowChartProps {
  chart: string;
  renderKey: string | number;
  active?: boolean;
}

export function MermaidFlowChart({ chart, renderKey, active = true }: MermaidFlowChartProps) {
  const mermaidRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [hasRenderedChart, setHasRenderedChart] = useState(false);
  const [contentSize, setContentSize] = useState({ width: 0, height: 0 });

  const measureChart = useCallback(() => {
    const root = mermaidRef.current;
    if (!root) return;
    const svg = root.querySelector("svg");
    if (!svg) return;
    const box = svg.getBBox();
    const width = box.width || svg.clientWidth;
    const height = box.height || svg.clientHeight;
    if (width > 0 && height > 0) {
      setContentSize({ width, height });
    }
  }, []);

  useEffect(() => {
    setScale(1);
    setHasRenderedChart(false);
    setContentSize({ width: 0, height: 0 });
  }, [chart, renderKey]);

  useEffect(() => {
    if (!chart || !mermaidRef.current || !active) return;

    mermaid.initialize({
      startOnLoad: false,
      theme: "neutral",
      securityLevel: "loose",
      flowchart: { useMaxWidth: true, htmlLabels: true, curve: "basis" },
    });

    const id = `mermaid-${renderKey}-${Date.now()}`;
    mermaidRef.current.innerHTML = "";
    setHasRenderedChart(false);

    mermaid
      .render(id, chart)
      .then(({ svg }) => {
        if (mermaidRef.current) {
          mermaidRef.current.innerHTML = svg;
          setHasRenderedChart(true);
          requestAnimationFrame(measureChart);
        }
      })
      .catch(() => {
        if (mermaidRef.current) {
          mermaidRef.current.textContent = "Could not render flowchart.";
          setHasRenderedChart(false);
        }
      });
  }, [chart, renderKey, active, measureChart]);

  const applyScale = useCallback((next: number | ((prev: number) => number)) => {
    setScale((prev) => clampScale(typeof next === "function" ? next(prev) : next));
  }, []);

  const handleWheel = useCallback(
    (e: React.WheelEvent<HTMLDivElement>) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const delta = e.deltaY > 0 ? -WHEEL_STEP : WHEEL_STEP;
      applyScale((prev) => prev + delta);
    },
    [applyScale],
  );

  return (
    <div className="mermaid-chart-shell">
      <div className="mermaid-viewport" onWheel={handleWheel}>
        <div
          className="mermaid-scroll-spacer"
          style={
            contentSize.width > 0 && contentSize.height > 0
              ? {
                  width: contentSize.width * scale,
                  height: contentSize.height * scale,
                }
              : undefined
          }
        >
          <div
            className="mermaid-zoom-root"
            ref={mermaidRef}
            style={{ transform: `scale(${scale})` }}
          />
        </div>
      </div>
      {hasRenderedChart && (
        <div className="mermaid-zoom-hud" aria-label="Diagram zoom">
          <div className="mermaid-zoom-btns">
            <button
              type="button"
              title="Zoom in"
              disabled={scale >= MAX_SCALE}
              onClick={() => applyScale((prev) => prev + BUTTON_STEP)}
            >
              +
            </button>
            <button
              type="button"
              title="Zoom out"
              disabled={scale <= MIN_SCALE}
              onClick={() => applyScale((prev) => prev - BUTTON_STEP)}
            >
              −
            </button>
            <button type="button" title="Reset to 100%" onClick={() => applyScale(1)}>
              1:1
            </button>
          </div>
          <span className="mermaid-zoom-label">{Math.round(scale * 100)}%</span>
          <span className="mermaid-zoom-hint">Ctrl + wheel to zoom</span>
        </div>
      )}
    </div>
  );
}
