/**
 * dashboard/src/components/DTSimView.jsx
 * ──────────────────────────────────────────
 * Digital Twin Simulation Panel — M/M/1 Queuing Model Visualization
 *
 * Shows:
 *   1. Approval status with improvement percentage
 *   2. M/M/1 queue metrics (ρ utilisation, queue length)
 *   3. Before → After KPI comparison with delta bars
 *   4. Recommendation from the queuing engine
 */

import { Cpu } from "lucide-react";

const KPI_UNITS = {
  dl_throughput_mbps: "Mbps",
  latency_ms: "ms",
  bler_pct: "%",
  rsrp_dbm: "dBm",
  handover_success_rate: "%",
  slice_utilisation_pct: "%",
};

const KPI_BETTER_IF = {
  dl_throughput_mbps: "higher",
  latency_ms: "lower",
  bler_pct: "lower",
  rsrp_dbm: "higher",
  handover_success_rate: "higher",
  slice_utilisation_pct: "lower",
};

function getDeltaColor(key, delta) {
  const dir = KPI_BETTER_IF[key] || "lower";
  const isGood = (dir === "higher" && delta > 0) || (dir === "lower" && delta < 0);
  if (Math.abs(delta) < 0.01) return "#64748b";
  return isGood ? "#10b981" : "#ef4444";
}

function formatDelta(delta) {
  const sign = delta > 0 ? "+" : "";
  return `${sign}${delta.toFixed(1)}`;
}

export function DTSimView({ simulation }) {
  const improvement = simulation ? Math.round(simulation.improvement_pct * 100) : 0;
  const qm = simulation?.queue_metrics;
  const recommendation = simulation?.recommendation;

  const cardStyle = {
    background: "rgba(15,23,42,0.9)",
    border: `1.5px solid ${simulation?.approved ? "#10b98140" : "#334155"}`,
    borderRadius: 12,
    padding: "16px 18px",
    fontFamily: "'IBM Plex Mono', 'Fira Code', monospace",
  };

  return (
    <section style={cardStyle}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <Cpu size={16} style={{ color: "#94a3b8" }} />
        <span style={{ fontSize: 12, fontWeight: 800, color: "#94a3b8", letterSpacing: "0.06em" }}>
          DIGITAL TWIN · M/M/1 ENGINE
        </span>
      </div>

      {!simulation && (
        <div style={{ color: "#334155", fontSize: 10, padding: "24px 0", textAlign: "center" }}>
          Awaiting twin simulation...
        </div>
      )}

      {simulation && (
        <>
          {/* Approval Badge */}
          <div style={{
            borderRadius: 8,
            padding: "10px 14px",
            fontWeight: 800,
            fontSize: 12,
            marginBottom: 12,
            background: simulation.approved ? "rgba(16,185,129,0.1)" : "rgba(239,68,68,0.1)",
            border: `1px solid ${simulation.approved ? "#10b98140" : "#ef444440"}`,
            color: simulation.approved ? "#10b981" : "#ef4444",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}>
            <span>{simulation.approved ? "✓ APPROVED" : "✗ ESCALATING"}</span>
            <span style={{ fontSize: 18, fontWeight: 900 }}>{improvement}%</span>
          </div>

          {/* M/M/1 Queue Metrics */}
          {qm && (
            <div style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 8,
              marginBottom: 12,
            }}>
              <QueueMetricCard
                label="UTILISATION (ρ)"
                before={qm.rho_before}
                after={qm.rho_after}
                format={(v) => (v * 100).toFixed(1) + "%"}
                isBetterLower
              />
              <QueueMetricCard
                label="QUEUE LENGTH (Lq)"
                before={qm.queue_length_before}
                after={qm.queue_length_after}
                format={(v) => v.toFixed(1)}
                isBetterLower
              />
            </div>
          )}

          {/* Before → After KPI Table */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 8, color: "#475569", letterSpacing: "0.08em", marginBottom: 8 }}>
              KPI IMPACT ANALYSIS
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {Object.entries(simulation.current_state || {}).slice(0, 6).map(([key, before]) => {
                const after = simulation.projected_state?.[key] ?? before;
                const delta = after - before;
                const deltaColor = getDeltaColor(key, delta);
                const unit = KPI_UNITS[key] || "";

                return (
                  <div key={key} style={{
                    display: "grid",
                    gridTemplateColumns: "120px 60px 20px 60px 50px",
                    gap: 6,
                    alignItems: "center",
                    fontSize: 10,
                    padding: "3px 6px",
                    borderRadius: 4,
                    background: Math.abs(delta) > 0.1 ? `${deltaColor}08` : "transparent",
                  }}>
                    <span style={{ color: "#94a3b8" }}>{key.replace(/_/g, " ")}</span>
                    <span style={{ color: "#64748b", textAlign: "right" }}>{Number(before).toFixed(1)}</span>
                    <span style={{ color: "#475569", textAlign: "center" }}>→</span>
                    <span style={{ color: "#e2e8f0", fontWeight: 700, textAlign: "right" }}>
                      {Number(after).toFixed(1)}
                    </span>
                    <span style={{
                      color: deltaColor,
                      fontWeight: 700,
                      textAlign: "right",
                      fontSize: 9,
                    }}>
                      {formatDelta(delta)} {unit}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Recommendation */}
          {recommendation && (
            <div style={{
              fontSize: 9,
              color: "#94a3b8",
              padding: "8px 10px",
              background: "#0f172a",
              borderRadius: 6,
              border: "1px solid #1e293b",
              lineHeight: 1.5,
            }}>
              <span style={{ fontSize: 7, color: "#475569", letterSpacing: "0.08em" }}>
                ENGINE OUTPUT
              </span>
              <br />
              {recommendation}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function QueueMetricCard({ label, before, after, format, isBetterLower }) {
  const delta = after - before;
  const isGood = isBetterLower ? delta < 0 : delta > 0;
  const color = Math.abs(delta) < 0.001 ? "#64748b" : isGood ? "#10b981" : "#ef4444";

  return (
    <div style={{
      background: "#0f172a",
      border: "1px solid #1e293b",
      borderRadius: 8,
      padding: "10px 12px",
      textAlign: "center",
    }}>
      <div style={{ fontSize: 7, color: "#475569", letterSpacing: "0.08em", marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 14, color: "#64748b" }}>{format(before)}</span>
        <span style={{ fontSize: 10, color: "#475569" }}>→</span>
        <span style={{ fontSize: 14, fontWeight: 800, color }}>{format(after)}</span>
      </div>
    </div>
  );
}
