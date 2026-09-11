import { useEffect, useState, type ReactNode } from "react";
import { Breadcrumbs } from "./Breadcrumbs";

export type AppView = "findings" | "scan";

interface AppShellProps {
  view: AppView;
  onViewChange: (view: AppView) => void;
  children: ReactNode;
  breadcrumbTail: string;
}

function HeaderClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <span className="header-timestamp" title="Current time">
      {now.toLocaleString(undefined, {
        month: "numeric",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
      })}
    </span>
  );
}

export function AppShell({ view, onViewChange, children, breadcrumbTail }: AppShellProps) {
  return (
    <div className="app-shell">
      <nav className="app-sidebar" aria-label="Main navigation">
        <button
          type="button"
          className={`sidebar-btn${view === "findings" ? " active" : ""}`}
          title="Order Replay"
          onClick={() => onViewChange("findings")}
        >
          🏠
        </button>
        <button
          type="button"
          className={`sidebar-btn${view === "scan" ? " active" : ""}`}
          title="Scan settings"
          onClick={() => onViewChange("scan")}
        >
          ⚙
        </button>
      </nav>
      <div className="app-main">
        <header className="app-header">
          <Breadcrumbs
            items={[
              { label: "Home", href: "#" },
              { label: "Error Analysis" },
              { label: breadcrumbTail },
            ]}
          />
          <div className="header-actions">
            <HeaderClock />
          </div>
        </header>
        <main className="app-content">{children}</main>
      </div>
    </div>
  );
}
