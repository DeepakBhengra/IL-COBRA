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
    getDefaults().then(setDefaults);
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
    if (!defaults) {
      setError("Scan configuration is still loading. Try again in a moment.");
      return;
    }

    setScanning(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await runScan({
        source_root: defaults.source_root,
        rules_path: defaults.rules_path,
        out_dir: defaults.out_dir,
        summarizer: "heuristic",
        error_code: classified.kind === "error_code" ? classified.value : "",
        error_field: classified.kind === "error_field" ? classified.value : "",
        corora_mappings: defaults.corora_mappings,
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
      <div className="metrics-row">
        <div className="metric-card">
          <div className="label">Findings</div>
          <div className="value">{metrics.findings}</div>
        </div>
        <div className="metric-card">
          <div className="label">Programs</div>
          <div className="value">{metrics.programs}</div>
        </div>
        <div className="metric-card">
          <div className="label">Error codes</div>
          <div className="value">{metrics.error_codes}</div>
        </div>
        <div className="metric-card">
          <div className="label">Source files</div>
          <div className="value">{metrics.source_files}</div>
        </div>
      </div>

      <TabBar
        active={filters.tab}
        counts={tabCounts}
        onChange={(tab) => updateFilter({ tab })}
      />

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
