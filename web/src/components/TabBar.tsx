import type { TabFilter } from "../types/findings";

const TABS: Array<{ id: TabFilter; label: string }> = [
  { id: "all", label: "All Findings" },
  { id: "two_char", label: "Two-char Codes" },
  { id: "patterns", label: "Patterns" },
  { id: "mapped", label: "Mapped" },
];

interface TabBarProps {
  active: TabFilter;
  counts: Record<TabFilter, number>;
  onChange: (tab: TabFilter) => void;
}

export function TabBar({ active, counts, onChange }: TabBarProps) {
  return (
    <div className="tab-bar" role="tablist">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          className={`tab-item${active === tab.id ? " active" : ""}`}
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
          <span className="tab-badge">{counts[tab.id] ?? 0}</span>
        </button>
      ))}
    </div>
  );
}
