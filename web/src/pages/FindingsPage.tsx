import { useCallback, useEffect, useState } from "react";
import { exportCsvUrl, getDefaults, getFindings, getMetrics, runScan } from "../api/client";
import type { DefaultConfig, FilterState, FindingRow, TabFilter } from "../types/findings";
import { classifyFocusedSearchInput } from "../utils/focusedSearch";
import { FilterDrawer } from "../components/FilterDrawer";
import { FindingDetail } from "../components/FindingDetail";
import { FindingsTable } from "../components/FindingsTable";
import { Pagination } from "../components/Pagination";
import { SearchToolbar } from "../components/SearchToolbar";
import { TabBar } from "../components/TabBar";

type MetricIconName = "findings" | "programs" | "codes" | "files";

const METRIC_ICON_PATHS: Record<MetricIconName, string> = {
  findings: "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  programs: "M8 6l-5 6 5 6M16 6l5 6-5 6",
  codes: "M4 9h16M4 15h16M10 3 8 21M16 3l-2 18",
  files: "M14 3v5h5M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z",
};

function MetricIcon({ name }: { name: MetricIconName }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={METRIC_ICON_PATHS[name]} />
    </svg>
  );
}

const DEFAULT_FILTERS: FilterState = {
  q: "",
  programs: [],
  errorCodes: "",
  fieldContains: "",
  tab: "all",
  page: 1,
  pageSize: 100,
};

interface FindingsPageProps {
  refreshKey: number;
  outDir?: string;
  onScanComplete?: () => void;
  onConfigureIngest?: () => void;
}

export function FindingsPage({ refreshKey, outDir, onScanComplete, onConfigureIngest }: FindingsPageProps) {
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);
  const [draftPrograms, setDraftPrograms] = useState<string[]>([]);
  const [draftErrorCodes, setDraftErrorCodes] = useState("");
  const [draftFieldContains, setDraftFieldContains] = useState("");
  const [rows, setRows] = useState<FindingRow[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [tabCounts, setTabCounts] = useState<Record<TabFilter, number>>({
    all: 0,
    two_char: 0,
    patterns: 0,
    mapped: 0,
  });
  const [metrics, setMetrics] = useState({
    findings: 0,
    programs: 0,
    error_codes: 0,
    source_files: 0,
  });
  const [allPrograms, setAllPrograms] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set());
  const [detailIndex, setDetailIndex] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [defaults, setDefaults] = useState<DefaultConfig | null>(null);
  const [dataEnabled, setDataEnabled] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getDefaults()
      .then((cfg) => {
        if (!cancelled) setDefaults(cfg);
      })
      .catch(() => {
        // Ignore here; the config is re-fetched on demand when the user searches,
        // so a transient failure on mount does not permanently block searching.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Enable loading after a scan/ingest completes.
  useEffect(() => {
    if (refreshKey > 0) {
      setDataEnabled(true);
    }
  }, [refreshKey]);

  // New scan/ingest replaces errors.jsonl; clear stale drawer index.
  useEffect(() => {
    setDetailIndex(null);
    setSelectedIndices(new Set());
  }, [refreshKey]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [findingsRes, metricsRes] = await Promise.all([
        getFindings(filters, outDir),
        getMetrics(filters, outDir),
      ]);
      setRows(findingsRes.rows);
      setTotal(findingsRes.total);
      setTotalPages(findingsRes.total_pages);
      setMetrics(metricsRes.metrics);
      setTabCounts(metricsRes.tab_counts);
      setAllPrograms(metricsRes.programs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load findings");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [filters, outDir, refreshKey]);

  useEffect(() => {
    if (!dataEnabled) {
      return;
    }
    loadData();
  }, [loadData, dataEnabled]);

  const handleRefresh = () => {
    setDataEnabled(true);
    void loadData();
  };

  useEffect(() => {
    setDraftPrograms(filters.programs);
    setDraftErrorCodes(filters.errorCodes);
    setDraftFieldContains(filters.fieldContains);
  }, [filterOpen]);

  const updateFilter = (patch: Partial<FilterState>) => {
    setFilters((prev) => ({ ...prev, ...patch, page: patch.page ?? 1 }));
  };

  const handleExport = () => {
    if (!dataEnabled) {
      return;
    }
    const indices = selectedIndices.size > 0 ? Array.from(selectedIndices) : [];
    const url = exportCsvUrl(filters, indices, outDir);
    window.open(url, "_blank");
  };

  const handleToggleRow = (index: number) => {
    setSelectedIndices((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const handleToggleAll = (checked: boolean) => {
    if (checked) {
      setSelectedIndices(new Set(rows.map((r) => r._index ?? -1).filter((i) => i >= 0)));
    } else {
      setSelectedIndices(new Set());
    }
  };

  const handleFocusedSearch = async (value: string) => {
    const classified = classifyFocusedSearchInput(value);
    if (classified.kind === "invalid") {
      setSuccess(null);
      setError(classified.message);
      return;
    }
    setScanning(true);
    setError(null);
    setSuccess(null);
    try {
      // Fetch the scan configuration on demand if the background load on mount
      // failed or has not resolved yet. This surfaces the real API error (e.g.
      // "Cannot reach the COBOL scanner API") instead of silently blocking.
      let config = defaults;
      if (!config) {
        config = await getDefaults();
        setDefaults(config);
      }
      const result = await runScan({
        source_root: config.source_root,
        rules_path: config.rules_path,
        out_dir: config.out_dir,
        summarizer: "heuristic",
        error_code: classified.kind === "error_code" ? classified.value : "",
        error_field: classified.kind === "error_field" ? classified.value : "",
        corora_mappings: config.corora_mappings,
      });
      setSuccess(
        `Scanned ${result.program_count} program(s), found ${result.finding_count} finding(s). Wrote ${result.table_name}.`,
      );
      setDetailIndex(null);
      setFilters((prev) => ({ ...prev, q: "", page: 1 }));
      setDataEnabled(true);
      onScanComplete?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Focused scan failed");
    } finally {
      setScanning(false);
    }
  };

  return (
    <>
      <div className="page-heading">
        <span className="page-eyebrow">Error Analysis</span>
        <h1 className="page-title">Error Findings</h1>
        <p className="page-subtitle">
          Scan COBOL programs for error-handling paths, then search, filter, and map findings to
          operational documentation.
        </p>
      </div>

      <div className="metrics-row">
        <div className="metric-card">
          <span className="metric-icon">
            <MetricIcon name="findings" />
          </span>
          <div className="metric-body">
            <div className="label">Findings</div>
            <div className="value">{metrics.findings}</div>
          </div>
        </div>
        <div className="metric-card">
          <span className="metric-icon">
            <MetricIcon name="programs" />
          </span>
          <div className="metric-body">
            <div className="label">Programs</div>
            <div className="value">{metrics.programs}</div>
          </div>
        </div>
        <div className="metric-card">
          <span className="metric-icon">
            <MetricIcon name="codes" />
          </span>
          <div className="metric-body">
            <div className="label">Error codes</div>
            <div className="value">{metrics.error_codes}</div>
          </div>
        </div>
        <div className="metric-card">
          <span className="metric-icon">
            <MetricIcon name="files" />
          </span>
          <div className="metric-body">
            <div className="label">Source files</div>
            <div className="value">{metrics.source_files}</div>
          </div>
        </div>
      </div>

      <TabBar
        active={filters.tab}
        counts={tabCounts}
        onChange={(tab) => updateFilter({ tab })}
      />

      <section className="search-panel">
        <h2 className="search-panel-title">Search Error Findings</h2>
        <p className="search-panel-subtitle">
          Enter a 2-character error code or an error field name and run a focused COBOL scan
        </p>
        <SearchToolbar
          query={filters.q}
          onQueryChange={(q) => updateFilter({ q })}
          onFocusedSearch={handleFocusedSearch}
          onRefresh={handleRefresh}
          onFilter={() => setFilterOpen(true)}
          onExport={handleExport}
          loading={loading}
          scanning={scanning}
        />
      </section>

      {success && <div className="alert alert-success">{success}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {!dataEnabled && !loading ? (
        <div className="alert alert-info">
          No results loaded yet. Run a scan from Scan Settings or use Search above, or click refresh
          to load existing results from disk.
        </div>
      ) : loading && rows.length === 0 ? (
        <div className="loading-overlay">
          <span className="spinner" /> Loading findings…
        </div>
      ) : (
        <>
          <FindingsTable
            rows={rows}
            selectedIndices={selectedIndices}
            onToggleRow={handleToggleRow}
            onToggleAll={handleToggleAll}
            onRowClick={(row) => {
              if (row._index === undefined || row._index === null) return;
              setDetailIndex(row._index);
            }}
            activeIndex={detailIndex ?? undefined}
          />
          <Pagination
            page={filters.page}
            pageSize={filters.pageSize}
            total={total}
            totalPages={totalPages}
            onPageChange={(page) => updateFilter({ page })}
            onPageSizeChange={(pageSize) => updateFilter({ pageSize, page: 1 })}
          />
        </>
      )}

      <FilterDrawer
        open={filterOpen}
        onClose={() => setFilterOpen(false)}
        programs={allPrograms}
        selectedPrograms={draftPrograms}
        errorCodes={draftErrorCodes}
        fieldContains={draftFieldContains}
        onProgramsChange={setDraftPrograms}
        onErrorCodesChange={setDraftErrorCodes}
        onFieldContainsChange={setDraftFieldContains}
        onApply={() => {
          updateFilter({
            programs: draftPrograms,
            errorCodes: draftErrorCodes,
            fieldContains: draftFieldContains,
          });
          setFilterOpen(false);
        }}
      />

      <FindingDetail
        index={detailIndex}
        outDir={outDir}
        onClose={() => setDetailIndex(null)}
        onConfigureIngest={() => {
          setDetailIndex(null);
          onConfigureIngest?.();
        }}
      />
    </>
  );
}
