import { Flame } from "lucide-react";

export function HeatmapView({ event }) {
  const weights = event?.attention_weights || {};
  return (
    <section className="panel">
      <div className="panel-title"><Flame size={18} /> Root Cause Heatmap</div>
      {Object.keys(weights).length === 0 && <div className="empty">No attribution yet</div>}
      {Object.entries(weights).map(([key, value]) => (
        <div className="heat-row" key={key}>
          <span>{key}</span>
          <div className="heat-track">
            <div className="heat-fill" style={{ width: `${value * 100}%`, opacity: 0.35 + value }} />
          </div>
          <strong>{Math.round(value * 100)}%</strong>
        </div>
      ))}
      {event?.top_cause && <div className="top-cause">Top cause: {event.top_cause}</div>}
    </section>
  );
}
