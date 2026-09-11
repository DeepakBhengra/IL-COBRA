import { useState } from "react";
import { AppShell, type AppView } from "./components/AppShell";
import { ScanSettings } from "./components/ScanSettings";
import { OrderReplayPage } from "./pages/OrderReplayPage";

export default function App() {
  const [view, setView] = useState<AppView>("findings");

  const handleScanComplete = () => {
    setView("findings");
  };

  return (
    <AppShell
      view={view}
      onViewChange={setView}
      breadcrumbTail={view === "findings" ? "Order Replay" : "Scan Settings"}
    >
      {view === "findings" ? <OrderReplayPage /> : <ScanSettings onScanComplete={handleScanComplete} />}
    </AppShell>
  );
}
