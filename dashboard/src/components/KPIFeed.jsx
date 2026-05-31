import { Activity } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const kpiDefs = [
  ["dl_throughput_mbps", "DL Mbps", "#45b36b"],
  ["latency_ms", "Latency", "#e2b93b"],
  ["bler_pct", "BLER", "#e35d5d"],
  ["rsrp_dbm", "RSRP", "#68a7ff"],
  ["handover_success_rate", "Handover", "#9b8cff"],
  ["slice_utilisation_pct", "Slice Util", "#ff8f4d"]
];

export function KPIFeed({ data }) {
  return (
    <section className="panel kpi-panel">
      <div className="panel-title"><Activity size={18} /> Live KPI Feed</div>
      <div className="kpi-grid">
        {kpiDefs.map(([key, label, color]) => (
          <div className="chart-tile" key={key}>
            <div className="chart-label">{label}</div>
            <ResponsiveContainer width="100%" height={116}>
              <LineChart data={data}>
                <XAxis dataKey="timestamp" hide />
                <YAxis width={36} tick={{ fontSize: 10 }} domain={["auto", "auto"]} />
                <Tooltip contentStyle={{ background: "#111827", border: "1px solid #263244" }} />
                <Line type="monotone" dataKey={key} dot={false} stroke={color} strokeWidth={2} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ))}
      </div>
    </section>
  );
}
