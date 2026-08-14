import type { FindingRow } from "../types/findings";
import { TABLE_COLUMNS } from "../types/findings";

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

interface FindingsTableProps {
  rows: FindingRow[];
  selectedIndices: Set<number>;
  onToggleRow: (index: number) => void;
  onToggleAll: (checked: boolean) => void;
  onRowClick: (row: FindingRow) => void;
  activeIndex?: number;
}

export function FindingsTable({
  rows,
  selectedIndices,
  onToggleRow,
  onToggleAll,
  onRowClick,
  activeIndex,
}: FindingsTableProps) {
  const allSelected = rows.length > 0 && rows.every((r) => selectedIndices.has(r._index ?? -1));

  if (rows.length === 0) {
    return <div className="empty-state">No findings found.</div>;
  }

  return (
    <div className="findings-table-wrap">
      <table className="findings-table">
        <thead>
          <tr>
            <th className="col-check">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={(e) => onToggleAll(e.target.checked)}
                aria-label="Select all rows"
              />
            </th>
            {TABLE_COLUMNS.map((col) => (
              <th key={col.key}>{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const idx = row._index ?? -1;
            const selected = activeIndex === idx;
            return (
              <tr
                key={idx}
                className={selected ? "selected" : ""}
                onClick={() => onRowClick(row)}
              >
                <td className="col-check" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selectedIndices.has(idx)}
                    onChange={() => onToggleRow(idx)}
                    aria-label={`Select row ${idx}`}
                  />
                </td>
                {TABLE_COLUMNS.map((col) => (
                  <td key={col.key}>{cell(row[col.key])}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
