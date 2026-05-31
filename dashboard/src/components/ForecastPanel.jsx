/**
 * dashboard/src/components/ForecastPanel.jsx
 * ────────────────────────────────────────────
 * Predictive Healing Panel for ASTRA NOC Dashboard
 *
 * Shows:
 *   1. 60-second risk trajectory (area chart — will the KPIs cross the threshold?)
 *   2. Seconds-to-anomaly countdown (if alert active)
 *   3. Confidence gauge
 *   4. At-risk KPI badges
 *   5. Prevention statistics counter (Prevented vs Healed)
 *
 * WebSocket events consumed:
 *   FORECAST_UPDATE    — risk curve + alert status
 *   PREVENTION_APPLIED — pre-emptive action taken
 *   PREVENTION_CONFIRMED — anomaly never materialised
 *   PREVENTION_SKIPPED — DT rejected or low confidence
 *
 * Props: none — all state from WebSocket via useWebSocket hook
 */

import { useState, useEffect, useRef } from "react";

// ── Recharts components ───────────────────────────────────────────────────
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer,
} from "recharts";

// ── Constants ─────────────────────────────────────────────────────────────
const THRESHOLD_LINE_COLOR = "#ef4444";
const WARN_LINE_COLOR      = "#f97316";
const SAFE_COLOR           = "#10b981";
const ALERT_COLOR          = "#ef4444";
const WARN_COLOR           = "#f97316";

export default function ForecastPanel({ wsLastMessage }) {
  const [forecast, setForecast]       = useState(null);
  const [prevStats, setPrevStats]     = useState({ prevented: 0, false_alarms: 0 });
  const [lastPrevention, setLastPrev] = useState(null);
  const [countdown, setCountdown]     = useState(null);
  const countdownRef                  = useRef(null);

  // ── WebSocket event handler ──────────────────────────────────────────
  useEffect(() => {
    if (!wsLastMessage) return;
    try {
      const msg = JSON.parse(wsLastMessage.data ?? wsLastMessage);
      switch (msg.type) {
        case "FORECAST_UPDATE":
          setForecast(msg);
          if (msg.preemptive_alert && msg.seconds_to_anomaly) {
            startCountdown(msg.seconds_to_anomaly);
          } else {
            clearCountdown();
          }
          break;
        case "PREVENTION_APPLIED":
        case "PREVENTION_CONFIRMED":
        case "PREVENTION_SKIPPED":
          setLastPrev(msg);
          if (msg.counters) setPrevStats(msg.counters);
          break;
        default:
          // update prevention stats from KPI_UPDATE if included
          if (msg.prevention_stats) setPrevStats(msg.prevention_stats);
      }
    } catch (_) {}
  }, [wsLastMessage]);

  // ── Countdown timer ──────────────────────────────────────────────────
  const startCountdown = (seconds) => {
    clearCountdown();
    setCountdown(seconds);
    countdownRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) { clearCountdown(); return null; }
        return prev - 1;
      });
    }, 1000);
  };
  const clearCountdown = () => {
    if (countdownRef.current) clearInterval(countdownRef.current);
    setCountdown(null);
  };
  useEffect(() => () => clearCountdown(), []);

  // ── Chart data ───────────────────────────────────────────────────────
  const chartData = forecast?.risk_curve_60s?.map((val, i) => ({
    t: `${i}s`,
    risk: parseFloat((val * 100).toFixed(2)),
  })) ?? [];

  const isAlert = forecast?.preemptive_alert ?? false;
  const confidence = forecast?.confidence ?? 0;
  const atRisk = forecast?.at_risk_kpis ?? [];

  // Threshold reference values (scaled to chart units)
  const THRESHOLD_VAL = 35;   // approx 3-sigma in chart units
  const WARN_VAL      = 22;   // 2-sigma

  // ── Styles ───────────────────────────────────────────────────────────
  const card = {
    background: "rgba(15,23,42,0.85)",
    border: `1.5px solid ${isAlert ? ALERT_COLOR : "#1e293b"}`,
    borderRadius: 12,
    padding: "16px 18px",
    fontFamily: "'IBM Plex Mono', 'Fira Code', monospace",
    boxShadow: isAlert ? `0 0 20px ${ALERT_COLOR}30` : "none",
    transition: "all 0.3s ease",
  };

  return (
    <div style={card}>
      {/* ── Header ──────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 16 }}>{isAlert ? "⚠" : "🔮"}</span>
          <span style={{ fontSize: 12, fontWeight: 800, color: isAlert ? ALERT_COLOR : "#94a3b8", letterSpacing: "0.06em" }}>
            PREDICTIVE HEALING
          </span>
          {isAlert && (
            <span style={{
              background: `${ALERT_COLOR}25`, border: `1px solid ${ALERT_COLOR}`,
              borderRadius: 4, padding: "2px 7px", fontSize: 9, fontWeight: 800,
              color: ALERT_COLOR, letterSpacing: "0.1em", animation: "pulse 1s infinite",
            }}>
              PRE-ANOMALY ALERT
            </span>
          )}
        </div>

        {/* Confidence badge */}
        <div style={{
          background: confidence > 0.8 ? "#10b98120" : "#f59e0b20",
          border: `1px solid ${confidence > 0.8 ? "#10b981" : "#f59e0b"}`,
          borderRadius: 20, padding: "3px 10px", fontSize: 9,
          color: confidence > 0.8 ? "#10b981" : "#f59e0b", fontWeight: 700,
        }}>
          CONFIDENCE: {(confidence * 100).toFixed(0)}%
        </div>
      </div>

      {/* ── Countdown + At-risk KPIs ─────────────────────────────────── */}
      {isAlert && (
        <div style={{
          display: "flex", alignItems: "center", gap: 12,
          background: `${ALERT_COLOR}10`, border: `1px solid ${ALERT_COLOR}30`,
          borderRadius: 8, padding: "10px 14px", marginBottom: 12,
        }}>
          {countdown !== null && (
            <div style={{ textAlign: "center", minWidth: 60 }}>
              <div style={{ fontSize: 28, fontWeight: 900, color: ALERT_COLOR, lineHeight: 1 }}>
                {countdown}s
              </div>
              <div style={{ fontSize: 8, color: "#64748b", letterSpacing: "0.08em" }}>
                TO ANOMALY
              </div>
            </div>
          )}
          <div>
            <div style={{ fontSize: 9, color: "#64748b", marginBottom: 5, letterSpacing: "0.06em" }}>
              AT-RISK KPIs
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {atRisk.map((kpi) => (
                <span key={kpi} style={{
                  background: `${ALERT_COLOR}20`, border: `1px solid ${ALERT_COLOR}50`,
                  borderRadius: 4, padding: "2px 7px", fontSize: 9,
                  color: "#fca5a5", fontWeight: 700,
                }}>
                  {kpi.replace(/_/g, " ")}
                </span>
              ))}
            </div>
            <div style={{ fontSize: 9, color: "#cbd5e1", marginTop: 6 }}>
              {forecast?.summary?.substring(0, 120)}...
            </div>
          </div>
        </div>
      )}

      {/* ── Risk Trajectory Chart ────────────────────────────────────── */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 8, color: "#475569", letterSpacing: "0.08em", marginBottom: 6 }}>
          60-SECOND KPI RISK TRAJECTORY
        </div>
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={100}>
            <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
              <defs>
                <linearGradient id="riskGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={isAlert ? ALERT_COLOR : SAFE_COLOR} stopOpacity={0.4} />
                  <stop offset="95%" stopColor={isAlert ? ALERT_COLOR : SAFE_COLOR} stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="2 4" stroke="#1e293b" />
              <XAxis dataKey="t" tick={{ fontSize: 7, fill: "#475569" }} interval={9} />
              <YAxis tick={{ fontSize: 7, fill: "#475569" }} domain={[0, 60]} />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #334155", fontSize: 9 }}
                formatter={(v) => [`${v}%`, "Risk"]}
              />
              <ReferenceLine y={THRESHOLD_VAL} stroke={THRESHOLD_LINE_COLOR} strokeDasharray="4 2"
                label={{ value: "ANOMALY", position: "right", fontSize: 7, fill: THRESHOLD_LINE_COLOR }} />
              <ReferenceLine y={WARN_VAL} stroke={WARN_LINE_COLOR} strokeDasharray="2 3"
                label={{ value: "WARN", position: "right", fontSize: 7, fill: WARN_LINE_COLOR }} />
              <Area type="monotone" dataKey="risk" stroke={isAlert ? ALERT_COLOR : SAFE_COLOR}
                strokeWidth={1.5} fill="url(#riskGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ height: 100, display: "flex", alignItems: "center", justifyContent: "center",
            color: "#334155", fontSize: 10 }}>
            Waiting for 30-step buffer to fill...
          </div>
        )}
      </div>

      {/* ── Prevention Statistics ────────────────────────────────────── */}
      <div style={{ borderTop: "1px solid #1e293b", paddingTop: 12 }}>
        <div style={{ fontSize: 8, color: "#475569", letterSpacing: "0.08em", marginBottom: 8 }}>
          PREVENTION STATISTICS (SESSION)
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          {[
            { label: "PREVENTED",   value: prevStats.prevented ?? 0,     color: "#10b981", icon: "🛡" },
            { label: "HEALED",      value: prevStats.healed ?? 0,         color: "#6366f1", icon: "⚕" },
            { label: "FALSE ALARMS",value: prevStats.false_alarms ?? 0,   color: "#f59e0b", icon: "🔔" },
          ].map((s) => (
            <div key={s.label} style={{
              flex: 1, textAlign: "center",
              background: `${s.color}0a`, border: `1px solid ${s.color}25`,
              borderRadius: 7, padding: "8px 6px",
            }}>
              <div style={{ fontSize: 9 }}>{s.icon}</div>
              <div style={{ fontSize: 20, fontWeight: 900, color: s.color, lineHeight: 1.2 }}>
                {s.value}
              </div>
              <div style={{ fontSize: 7.5, color: "#64748b", marginTop: 1, letterSpacing: "0.06em" }}>
                {s.label}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Last Prevention Event ────────────────────────────────────── */}
      {lastPrevention && (
        <div style={{
          marginTop: 10,
          background: lastPrevention.type === "PREVENTION_APPLIED"
            ? "rgba(16,185,129,0.08)" : "rgba(100,116,139,0.08)",
          border: `1px solid ${lastPrevention.type === "PREVENTION_APPLIED" ? "#10b981" : "#334155"}30`,
          borderRadius: 6, padding: "8px 10px",
        }}>
          <div style={{ fontSize: 8, color: "#475569", letterSpacing: "0.06em", marginBottom: 3 }}>
            LAST EVENT · {lastPrevention.timestamp?.substring(11, 19) ?? ""}
          </div>
          <div style={{ fontSize: 9, color: "#cbd5e1" }}>
            {lastPrevention.type === "PREVENTION_APPLIED"
              ? `✓ Pre-emptive ${lastPrevention.action_type} applied`
              : lastPrevention.type === "PREVENTION_CONFIRMED"
              ? "✓ Anomaly never materialised — prevention confirmed"
              : `↷ Skipped: ${lastPrevention.reason}`
            }
          </div>
        </div>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
}
