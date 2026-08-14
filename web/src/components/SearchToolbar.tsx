interface SearchToolbarProps {
  query: string;
  onQueryChange: (q: string) => void;
  onFocusedSearch: (value: string) => void;
  onRefresh: () => void;
  onFilter: () => void;
  onExport: () => void;
  loading?: boolean;
  scanning?: boolean;
}

export function SearchToolbar({
  query,
  onQueryChange,
  onFocusedSearch,
  onRefresh,
  onFilter,
  onExport,
  loading,
  scanning,
}: SearchToolbarProps) {
  const busy = loading || scanning;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onFocusedSearch(query);
  };

  return (
    <>
      <form className="search-toolbar" onSubmit={handleSubmit}>
        <div className="search-input-wrap">
          <span className="search-icon" aria-hidden="true">
            🔍
          </span>
          <input
            type="search"
            className="search-input"
            placeholder="Error code (EV) or error field (ERROR-SHIP-VIA)"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            disabled={scanning}
          />
          {query && (
            <button
              type="button"
              className="search-clear"
              aria-label="Clear search"
              onClick={() => onQueryChange("")}
              disabled={scanning}
            >
              ×
            </button>
          )}
        </div>
        <button type="submit" className="outline-btn" disabled={busy || !query.trim()}>
          {scanning ? (
            <>
              <span className="spinner" /> Scanning…
            </>
          ) : (
            "Search"
          )}
        </button>
        <button
          type="button"
          className="icon-btn"
          title="Refresh"
          onClick={onRefresh}
          disabled={busy}
        >
          {loading && !scanning ? <span className="spinner" /> : "↻"}
        </button>
        <button type="button" className="outline-btn" onClick={onExport} disabled={scanning}>
          Export
        </button>
        <button type="button" className="outline-btn" onClick={onFilter} disabled={scanning}>
          ☰ Filter
        </button>
      </form>
      <p className="hint search-toolbar-hint">
        Press Search or Enter to run a focused COBOL scan. Use a 2-character code (e.g. EV) or an
        error field name with hyphens (e.g. ERROR-SHIP-VIA, max 30 characters).
      </p>
    </>
  );
}
