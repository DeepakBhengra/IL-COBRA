interface FilterDrawerProps {
  open: boolean;
  onClose: () => void;
  programs: string[];
  selectedPrograms: string[];
  errorCodes: string;
  fieldContains: string;
  onProgramsChange: (programs: string[]) => void;
  onErrorCodesChange: (codes: string) => void;
  onFieldContainsChange: (value: string) => void;
  onApply: () => void;
}

export function FilterDrawer({
  open,
  onClose,
  programs,
  selectedPrograms,
  errorCodes,
  fieldContains,
  onProgramsChange,
  onErrorCodesChange,
  onFieldContainsChange,
  onApply,
}: FilterDrawerProps) {
  if (!open) return null;

  const toggleProgram = (program: string) => {
    if (selectedPrograms.includes(program)) {
      onProgramsChange(selectedPrograms.filter((p) => p !== program));
    } else {
      onProgramsChange([...selectedPrograms, program]);
    }
  };

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="dialog" aria-label="Filters">
        <div className="drawer-header">
          <h2>Filter</h2>
          <button type="button" className="drawer-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="drawer-body">
          <div className="filter-group">
            <label>Programs</label>
            <div className="filter-programs">
              {programs.length === 0 ? (
                <span style={{ color: "var(--text-muted)" }}>No programs loaded</span>
              ) : (
                programs.map((p) => (
                  <label key={p}>
                    <input
                      type="checkbox"
                      checked={selectedPrograms.includes(p)}
                      onChange={() => toggleProgram(p)}
                    />
                    {p}
                  </label>
                ))
              )}
            </div>
          </div>
          <div className="filter-group">
            <label htmlFor="filter-error-codes">Error codes</label>
            <input
              id="filter-error-codes"
              type="text"
              placeholder="e.g. E1 or E1, X2"
              value={errorCodes}
              onChange={(e) => onErrorCodesChange(e.target.value)}
            />
            <p className="hint">
              One or more 2-character codes, comma or space separated.
            </p>
          </div>
          <div className="filter-group">
            <label htmlFor="filter-field">Error field contains</label>
            <input
              id="filter-field"
              type="text"
              placeholder="CORORA-R-… substring"
              maxLength={30}
              value={fieldContains}
              onChange={(e) => onFieldContainsChange(e.target.value)}
            />
          </div>
          <button type="button" className="primary-btn" onClick={onApply}>
            Apply Filters
          </button>
        </div>
      </aside>
    </>
  );
}
