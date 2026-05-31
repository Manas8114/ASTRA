import { Network } from "lucide-react";

export function TopologyView({ events }) {
  const latest = events.find((e) => e.type === "HEALING_APPLIED" || e.type === "ANOMALY_DETECTED");
  const status = latest?.type === "HEALING_APPLIED" ? "healing" : latest ? "anomalous" : "normal";
  return (
    <section className="panel">
      <div className="panel-title"><Network size={18} /> Multi-Cell Topology</div>
      <div className="cells">
        {["cell_001", "cell_002", "cell_003", "cell_004"].map((cell, idx) => (
          <div className="cell" key={cell}>
            <span className={`dot ${idx === 0 ? status : "normal"}`} />
            <strong>{cell}</strong>
            <small>{idx === 0 ? status : "normal"}</small>
          </div>
        ))}
      </div>
    </section>
  );
}
