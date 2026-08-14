import { useEffect, useState } from "react";
import { getDefaults } from "./api/client";
import { AppShell, type AppView } from "./components/AppShell";
import { ScanSettings } from "./components/ScanSettings";
import { FindingsPage } from "./pages/FindingsPage";
import type { DefaultConfig } from "./types/findings";

export default function App() {
  const [view, setView] = useState<AppView>("findings");
  const [classicUiUrl, setClassicUiUrl] = useState("http://localhost:8501");
  const [outDir, setOutDir] = useState<string | undefined>();
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    getDefaults().then((cfg: DefaultConfig) => {
      setClassicUiUrl(cfg.classic_ui_url);
      setOutDir(cfg.out_dir);
    });
  }, []);

  const handleScanComplete = () => {
    getDefaults().then((cfg: DefaultConfig) => setOutDir(cfg.out_dir));
    setRefreshKey((k) => k + 1);
    setView("findings");
  };

  const handleConfigureIngest = () => {
    setView("scan");
  };

  return (
    <AppShell
      view={view}
      onViewChange={setView}
      classicUiUrl={classicUiUrl}
      breadcrumbTail={view === "findings" ? "Error Findings" : "Scan Settings"}
    >
      {view === "findings" ? (
        <FindingsPage
          refreshKey={refreshKey}
          outDir={outDir}
          onScanComplete={handleScanComplete}
          onConfigureIngest={handleConfigureIngest}
        />
      ) : (
        <ScanSettings onScanComplete={handleScanComplete} />
      )}
    </AppShell>
  );
}
