import React from "react";
import { createRoot } from "react-dom/client";
import { RadioTower } from "lucide-react";
import { KPIFeed } from "./components/KPIFeed.jsx";
import { AnomalyTimeline } from "./components/AnomalyTimeline.jsx";
import { XAIAttribution } from "./components/XAIAttribution.jsx";
import { DTSimView } from "./components/DTSimView.jsx";
import { HealingLog } from "./components/HealingLog.jsx";
import { TopologyView } from "./components/TopologyView.jsx";
import { useWebSocket } from "./hooks/useWebSocket.js";
import { NocControls } from "./components/NocControls.jsx";
import ForecastPanel from "./components/ForecastPanel.jsx";
import RootCausePanel from "./components/RootCausePanel.jsx";
import "./styles.css";

function App() {
  const live = useWebSocket();
  return (
    <main>
      <header>
        <div>
          <h1><RadioTower size={28} /> ASTRA NOC</h1>
          <p>Autonomous 5G RAN self-healing dashboard</p>
        </div>
        <span className={`connection ${live.connected ? "on" : "off"}`}>{live.connected ? "connected" : "offline"}</span>
      </header>
      <KPIFeed data={live.kpis} />
      <div className="grid">
        <NocControls />
        <ForecastPanel wsLastMessage={live.lastMessage} />
        <AnomalyTimeline anomalies={live.anomalies} />
        <RootCausePanel />
        <XAIAttribution event={live.attribution} />
        <DTSimView simulation={live.simulation} />
        <HealingLog healing={live.healing} />
        <TopologyView events={live.events} kpis={live.kpis} simulation={live.simulation} />
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
