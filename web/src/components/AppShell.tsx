import type { ReactNode } from "react";
import { Breadcrumbs } from "./Breadcrumbs";

export type AppView = "findings" | "scan";

interface AppShellProps {
  view: AppView;
  onViewChange: (view: AppView) => void;
  classicUiUrl: string;
  children: ReactNode;
  breadcrumbTail: string;
}

export function AppShell({
  view,
  onViewChange,
  classicUiUrl,
  children,
  breadcrumbTail,
}: AppShellProps) {
  return (
    <div className="app-shell">
      <nav className="app-sidebar" aria-label="Main navigation">
        <button
          type="button"
          className={`sidebar-btn${view === "findings" ? " active" : ""}`}
          title="Findings"
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
              { label: "COBOL Scanner" },
              { label: breadcrumbTail },
            ]}
          />
          <div className="header-actions">
            <span className="ui-build-id" title="Frontend bundle build time">
              UI {typeof __APP_BUILD_ID__ !== "undefined" ? __APP_BUILD_ID__ : "dev"}
            </span>
            <a
              href={classicUiUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="classic-link"
            >
              Switch to Classic UI ↗
            </a>
          </div>
        </header>
        <main className="app-content">{children}</main>
      </div>
    </div>
  );
}
