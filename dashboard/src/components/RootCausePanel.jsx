/**
 * dashboard/src/components/RootCausePanel.jsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Phase 7 — CR²E Root Cause Panel
 *
 * Displays the latest RootCauseReport from the CR²E WebSocket stream.
 * Mounted in the existing ASTRA NOC dashboard (App.jsx) — no separate UI.
 *
 * Data flow:
 *   CR²E service (ws://localhost:8001/cr2e/ws)
 *     → ROOT_CAUSE_REPORT JSON event
 *       → this panel renders ranked causes + counterfactual plan + NL explanation
 *
 * Anti-fabrication: every number is displayed with its data_provenance_tag.
 * No number is shown without the tag badge.
 */

import { useState, useEffect, useRef } from "react";

const CR2E_WS_URL =
  (typeof window !== "undefined" && window.CR2E_WS_URL) ||
  "ws://localhost:8001/cr2e/ws";

// ── Tag badge colours ──────────────────────────────────────────────────────
function tagColour(tag) {
  if (!tag) return "#555";
  if (tag.includes("REAL:testbed")) return "#22c55e";
  if (tag.includes("REAL:injected")) return "#3b82f6";
  if (tag.includes("SYNTHETIC")) return "#f59e0b";
  return "#6b7280";
}

function ProvenanceTag({ tag }) {
  return (
    <span
      style={{
        background: tagColour(tag),
        color: "#fff",
        borderRadius: "4px",
        padding: "1px 6px",
        fontSize: "0.65rem",
        fontFamily: "monospace",
        marginLeft: "6px",
        whiteSpace: "nowrap",
      }}
    >
      {tag || "[UNKNOWN]"}
    </span>
  );
}

// ── Confidence interval bar ────────────────────────────────────────────────
function CIBar({ ate, ciLower, ciUpper, isSignificant }) {
  const significant = isSignificant;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
      <span
        style={{
          fontFamily: "monospace",
          fontSize: "0.78rem",
          color: significant ? "#22c55e" : "#f59e0b",
        }}
      >
        ATE {ate >= 0 ? "+" : ""}{ate.toFixed(4)}
      </span>
      <span
        style={{
          fontFamily: "monospace",
          fontSize: "0.68rem",
          color: "#9ca3af",
        }}
      >
        95%CI [{ciLower.toFixed(3)}, {ciUpper.toFixed(3)}]
      </span>
      {significant && (
        <span style={{ color: "#22c55e", fontSize: "0.7rem" }}>✓ significant</span>
      )}
      {!significant && (
        <span style={{ color: "#f59e0b", fontSize: "0.7rem" }}>⚠ CI contains 0</span>
      )}
    </div>
  );
}

// ── Main panel ─────────────────────────────────────────────────────────────
export default function RootCausePanel() {
  const [report, setReport] = useState(null);
  const [connected, setConnected] = useState(false);
  const [lastUpdateAt, setLastUpdateAt] = useState(null);
  const [wsError, setWsError] = useState(null);
  const wsRef = useRef(null);

  useEffect(() => {
    let reconnectTimer = null;

    function connect() {
      try {
        const ws = new WebSocket(CR2E_WS_URL);
        wsRef.current = ws;

        ws.onopen = () => {
          setConnected(true);
          setWsError(null);
        };

        ws.onmessage = (evt) => {
          try {
            const data = JSON.parse(evt.data);
            setReport(data);
            setLastUpdateAt(new Date().toLocaleTimeString());
          } catch (e) {
            console.warn("CR²E WS parse error:", e);
          }
        };

        ws.onclose = () => {
          setConnected(false);
          // Reconnect after 5 seconds
          reconnectTimer = setTimeout(connect, 5000);
        };

        ws.onerror = () => {
          setWsError("CR²E service unreachable — retrying…");
          ws.close();
        };
      } catch (e) {
        setWsError(`WebSocket error: ${e.message}`);
        reconnectTimer = setTimeout(connect, 5000);
      }
    }

    connect();
    return () => {
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, []);

  // ── Render: disconnected / no report ────────────────────────────────────
  if (!connected || !report) {
    return (
      <div
        style={{
          background: "#1e1e2e",
          border: "1px solid #374151",
          borderRadius: "10px",
          padding: "18px 20px",
          color: "#9ca3af",
          fontSize: "0.85rem",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              background: connected ? "#22c55e" : "#ef4444",
              display: "inline-block",
            }}
          />
          <strong style={{ color: "#e2e8f0" }}>CR²E — Root Cause Analysis</strong>
        </div>
        <div style={{ marginTop: "10px" }}>
          {wsError
            ? wsError
            : connected
            ? "Waiting for first ASTRA anomaly event…"
            : "Connecting to CR²E service (ws://localhost:8001/cr2e/ws)…"}
        </div>
      </div>
    );
  }

  const { fault_id, cell_id, anomaly_type, top_cause, ranked_causes,
          data_provenance_tag, nl_explanation, counterfactual_plan } = report;

  return (
    <div
      style={{
        background: "#1e1e2e",
        border: "1px solid #374151",
        borderRadius: "10px",
        padding: "18px 20px",
        color: "#e2e8f0",
        fontSize: "0.85rem",
        fontFamily: "Inter, system-ui, sans-serif",
      }}
    >
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "12px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              background: "#22c55e",
              display: "inline-block",
            }}
          />
          <strong style={{ color: "#e2e8f0", fontSize: "0.95rem" }}>
            CR²E — Root Cause Analysis
          </strong>
        </div>
        <ProvenanceTag tag={data_provenance_tag} />
      </div>

      {/* ── Fault metadata ───────────────────────────────────────────────── */}
      <div
        style={{
          background: "#111827",
          borderRadius: "6px",
          padding: "8px 12px",
          marginBottom: "12px",
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: "6px",
          fontSize: "0.78rem",
        }}
      >
        <div>
          <span style={{ color: "#6b7280" }}>Fault ID: </span>
          <span style={{ fontFamily: "monospace" }}>{fault_id}</span>
        </div>
        <div>
          <span style={{ color: "#6b7280" }}>Cell: </span>
          <span>{cell_id}</span>
        </div>
        <div>
          <span style={{ color: "#6b7280" }}>Type: </span>
          <span
            style={{
              color: "#f97316",
              fontWeight: 600,
            }}
          >
            {anomaly_type}
          </span>
        </div>
      </div>

      {/* ── Top cause badge ───────────────────────────────────────────────── */}
      <div style={{ marginBottom: "12px" }}>
        <span style={{ color: "#9ca3af", fontSize: "0.78rem" }}>Top root cause: </span>
        <span
          style={{
            background: "#7c3aed",
            color: "#fff",
            padding: "2px 10px",
            borderRadius: "12px",
            fontWeight: 700,
            fontSize: "0.82rem",
          }}
        >
          {top_cause || "undetermined"}
        </span>
      </div>

      {/* ── Ranked causes ─────────────────────────────────────────────────── */}
      {ranked_causes && ranked_causes.length > 0 && (
        <div style={{ marginBottom: "14px" }}>
          <div
            style={{
              color: "#6b7280",
              fontSize: "0.75rem",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              marginBottom: "6px",
            }}
          >
            Ranked Causes
          </div>
          {ranked_causes.map((rc) => (
            <div
              key={rc.kpi}
              style={{
                background: rc.is_significant ? "#111827" : "#1f2937",
                border: `1px solid ${rc.is_significant ? "#374151" : "#1f2937"}`,
                borderRadius: "6px",
                padding: "8px 12px",
                marginBottom: "6px",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span
                    style={{
                      background: "#374151",
                      borderRadius: "50%",
                      width: "20px",
                      height: "20px",
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "0.7rem",
                      fontWeight: 700,
                      color: "#e2e8f0",
                    }}
                  >
                    {rc.rank}
                  </span>
                  <span style={{ fontWeight: 600, color: "#c4b5fd" }}>
                    {rc.kpi}
                  </span>
                  <span style={{ color: "#6b7280", fontSize: "0.75rem" }}>
                    → {rc.outcome_kpi}
                  </span>
                </div>
                <ProvenanceTag tag={rc.data_provenance_tag} />
              </div>
              <div style={{ marginTop: "4px", paddingLeft: "28px" }}>
                <CIBar
                  ate={rc.ate}
                  ciLower={rc.ci_lower}
                  ciUpper={rc.ci_upper}
                  isSignificant={rc.is_significant}
                />
                {!rc.all_refutations_passed && (
                  <div
                    style={{
                      color: "#f59e0b",
                      fontSize: "0.7rem",
                      marginTop: "2px",
                    }}
                  >
                    ⚠ Some refutation tests did not pass — interpret with caution
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Counterfactual plan ─────────────────────────────────────────── */}
      {counterfactual_plan && counterfactual_plan.steps && counterfactual_plan.steps.length > 0 && (
        <div style={{ marginBottom: "14px" }}>
          <div
            style={{
              color: "#6b7280",
              fontSize: "0.75rem",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              marginBottom: "6px",
            }}
          >
            Prescriptive Intervention
            {counterfactual_plan.is_achievable && (
              <span style={{ color: "#22c55e", marginLeft: "8px", textTransform: "none" }}>
                ✓ target achievable
              </span>
            )}
          </div>
          {counterfactual_plan.steps.map((step, i) => (
            <div
              key={step.kpi}
              style={{
                background: "#0f172a",
                borderRadius: "6px",
                padding: "8px 12px",
                marginBottom: "6px",
                fontSize: "0.78rem",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span>
                  <strong style={{ color: "#38bdf8" }}>{step.kpi}</strong>
                  {" "}Δ{" "}
                  <span
                    style={{
                      fontFamily: "monospace",
                      color: step.delta >= 0 ? "#22c55e" : "#f87171",
                    }}
                  >
                    {step.delta >= 0 ? "+" : ""}{step.delta.toFixed(4)}
                  </span>
                  <span style={{ color: "#6b7280", marginLeft: "6px" }}>
                    95%CI [{step.delta_ci_lower.toFixed(3)}, {step.delta_ci_upper.toFixed(3)}]
                  </span>
                </span>
                <span style={{ color: "#a78bfa" }}>
                  ~{step.expected_outcome_improvement_pct.toFixed(0)}% resolution
                </span>
              </div>
              <div style={{ color: "#6b7280", fontSize: "0.7rem", marginTop: "2px" }}>
                ASTRA action hint: <strong>{step.astra_action_hint}</strong>
                <ProvenanceTag tag={step.data_provenance_tag} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── NL Explanation ────────────────────────────────────────────────── */}
      {nl_explanation && (
        <div
          style={{
            background: "#0f2a1e",
            borderLeft: "3px solid #22c55e",
            borderRadius: "0 6px 6px 0",
            padding: "10px 14px",
            fontSize: "0.82rem",
            color: "#d1fae5",
            fontStyle: "italic",
          }}
        >
          {nl_explanation}
        </div>
      )}

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <div
        style={{
          marginTop: "10px",
          fontSize: "0.68rem",
          color: "#4b5563",
          textAlign: "right",
        }}
      >
        Last updated: {lastUpdateAt} · CR²E v0.1.0
      </div>
    </div>
  );
}
