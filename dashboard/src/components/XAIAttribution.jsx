/**
 * dashboard/src/components/XAIAttribution.jsx
 * ─────────────────────────────────────────────
 * Explainable AI Attribution Panel for ASTRA NOC Dashboard
 *
 * Replaces the basic HeatmapView with a proper XAI visualization:
 *   1. Sorted horizontal bar chart of per-KPI anomaly contribution
 *   2. Top-cause callout with natural-language explanation
 *   3. Color gradient from safe (teal) → warning (amber) → critical (red)
 *   4. Animated bars on data change
 *
 * Consumes the `attribution` object from useWebSocket which contains:
 *   - attention_weights: { kpi_name: float }
 *   - top_cause: string
 *   - explanation: string
 *   - anomaly_type: string
 *   - confidence: float
 */

import { useState, useEffect, useRef } from "react";

const KPI_LABELS = {
  bler_pct: "Block Error Rate",
  rsrp_dbm: "Signal Power (RSRP)",
  latency_ms: "Latency",
  dl_throughput_mbps: "DL Throughput",
  slice_utilisation_pct: "Slice Utilisation",
  handover_success_rate: "Handover Success",
};

function getBarColor(pct) {
  if (pct >= 40) return "#ef4444";
  if (pct >= 25) return "#f97316";
  if (pct >= 15) return "#f59e0b";
  return "#10b981";
}

function getBarGlow(pct) {
  if (pct >= 40) return "0 0 12px rgba(239,68,68,0.4)";
  if (pct >= 25) return "0 0 8px rgba(249,115,22,0.3)";
  return "none";
}

export function XAIAttribution({ event }) {
  const weights = event?.attention_weights || {};
  const [animatedWidths, setAnimatedWidths] = useState({});
  const prevWeightsRef = useRef({});

  const sorted = Object.entries(weights)
    .map(([key, value]) => ({
      key,
      label: KPI_LABELS[key] || key.replace(/_/g, " "),
      pct: Math.round(value * 100),
      raw: value,
    }))
    .sort((a, b) => b.raw - a.raw);

  useEffect(() => {
    if (Object.keys(weights).length === 0) return;
    // Animate from 0 on first render or from previous values
    const prev = prevWeightsRef.current;
    const startWidths = {};
    sorted.forEach((s) => {
      startWidths[s.key] = prev[s.key] || 0;
    });
    setAnimatedWidths(startWidths);

    // Trigger animation to actual values
    const raf = requestAnimationFrame(() => {
      const finalWidths = {};
      sorted.forEach((s) => {
        finalWidths[s.key] = s.pct;
      });
      setAnimatedWidths(finalWidths);
    });

    prevWeightsRef.current = {};
    sorted.forEach((s) => {
      prevWeightsRef.current[s.key] = s.pct;
    });

    return () => cancelAnimationFrame(raf);
  }, [JSON.stringify(weights)]);

  const topCause = event?.top_cause;
  const explanation = event?.explanation;
  const anomalyType = event?.anomaly_type;
  const confidence = event?.confidence;

  const cardStyle = {
    background: "rgba(15,23,42,0.9)",
    border: `1.5px solid ${topCause ? "#334155" : "#1e293b"}`,
    borderRadius: 12,
    padding: "16px 18px",
    fontFamily: "'IBM Plex Mono', 'Fira Code', monospace",
  };

  return (
    <section style={cardStyle}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 16 }}>🧠</span>
          <span style={{
            fontSize: 12, fontWeight: 800,
            color: "#94a3b8", letterSpacing: "0.06em",
          }}>
            EXPLAINABLE AI · ROOT CAUSE
          </span>
        </div>
        {anomalyType && (
          <span style={{
            background: "#ef444420",
            border: "1px solid #ef444460",
            borderRadius: 4,
            padding: "2px 8px",
            fontSize: 9,
            fontWeight: 800,
            color: "#fca5a5",
            letterSpacing: "0.08em",
          }}>
            {anomalyType}
          </span>
        )}
      </div>

      {/* Empty state */}
      {sorted.length === 0 && (
        <div style={{
          color: "#334155", fontSize: 10, padding: "24px 0",
          textAlign: "center", letterSpacing: "0.04em",
        }}>
          Awaiting anomaly detection for attribution analysis...
        </div>
      )}

      {/* Attribution Bars */}
      {sorted.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {sorted.map((item, idx) => {
            const isTop = item.key === topCause;
            const barWidth = animatedWidths[item.key] ?? item.pct;
            const barColor = getBarColor(item.pct);

            return (
              <div key={item.key} style={{
                display: "grid",
                gridTemplateColumns: "130px 1fr 44px",
                gap: 10,
                alignItems: "center",
                padding: isTop ? "6px 8px" : "4px 8px",
                background: isTop ? `${barColor}08` : "transparent",
                border: isTop ? `1px solid ${barColor}25` : "1px solid transparent",
                borderRadius: 6,
                transition: "all 0.3s ease",
              }}>
                {/* KPI Label */}
                <div style={{
                  fontSize: 10,
                  color: isTop ? "#f1f5f9" : "#94a3b8",
                  fontWeight: isTop ? 700 : 400,
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                }}>
                  {isTop && <span style={{ fontSize: 8, color: barColor }}>▶</span>}
                  {item.label}
                </div>

                {/* Bar Track */}
                <div style={{
                  height: isTop ? 14 : 10,
                  background: "#1e293b",
                  borderRadius: 999,
                  overflow: "hidden",
                  position: "relative",
                }}>
                  <div style={{
                    height: "100%",
                    width: `${Math.min(barWidth, 100)}%`,
                    background: `linear-gradient(90deg, ${barColor}90, ${barColor})`,
                    borderRadius: 999,
                    transition: "width 0.6s cubic-bezier(0.25,0.46,0.45,0.94)",
                    boxShadow: getBarGlow(item.pct),
                  }} />
                </div>

                {/* Percentage */}
                <div style={{
                  fontSize: 11,
                  fontWeight: 800,
                  color: barColor,
                  textAlign: "right",
                  fontVariantNumeric: "tabular-nums",
                }}>
                  {item.pct}%
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Top Cause Explanation */}
      {explanation && (
        <div style={{
          marginTop: 12,
          padding: "10px 12px",
          background: "rgba(239,68,68,0.06)",
          border: "1px solid rgba(239,68,68,0.15)",
          borderRadius: 8,
        }}>
          <div style={{
            fontSize: 8,
            color: "#64748b",
            letterSpacing: "0.08em",
            marginBottom: 4,
          }}>
            AI EXPLANATION
          </div>
          <div style={{
            fontSize: 11,
            color: "#e2e8f0",
            lineHeight: 1.5,
          }}>
            {explanation}
          </div>
          {confidence != null && (
            <div style={{
              fontSize: 9,
              color: "#64748b",
              marginTop: 4,
            }}>
              Classification confidence: {(confidence * 100).toFixed(0)}%
            </div>
          )}
        </div>
      )}
    </section>
  );
}
