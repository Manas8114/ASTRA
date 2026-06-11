import { useState, useEffect } from "react";
import { Download, Wrench } from "lucide-react";

export function HealingLog({ healing = [] }) {
  const safeHealing = Array.isArray(healing) ? healing : [];
  const [startIndex, setStartIndex] = useState(0);

  // Auto reset to newest (index 0) when a new healing event is logged
  useEffect(() => {
    setStartIndex(0);
  }, [safeHealing.length]);

  const avg = safeHealing.length
    ? safeHealing.reduce((sum, item) => sum + Number(item.mttr_seconds || 0), 0) / safeHealing.length
    : 0;

  const formatTime = (timeStr) => {
    if (!timeStr) return "N/A";
    const date = new Date(timeStr);
    return isNaN(date.getTime()) ? "N/A" : date.toLocaleTimeString();
  };

  const exportCsv = () => {
    if (safeHealing.length === 0) return;
    const rows = [
      ["timestamp", "anomaly_type", "action_type", "mttr_seconds", "result"],
      ...safeHealing.map((h) => [h.timestamp, h.anomaly_type, h.action_type, h.mttr_seconds, h.result])
    ];
    const blob = new Blob([rows.map((r) => r.join(",")).join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "astra-healing-log.csv";
    a.click();
  };

  const displayedHealing = safeHealing.slice(startIndex, startIndex + 5);
  const maxSliderValue = Math.max(0, safeHealing.length - 5);

  return (
    <section className="panel">
      <div className="panel-title">
        <Wrench size={18} /> Healing Log 
        {safeHealing.length > 0 && (
          <button onClick={exportCsv} title="Export CSV">
            <Download size={16} />
          </button>
        )}
      </div>
      <div className="metric">Average MTTR: {avg.toFixed(1)}s</div>
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Anomaly</th>
            <th>Action</th>
            <th>MTTR</th>
          </tr>
        </thead>
        <tbody>
          {safeHealing.length === 0 ? (
            <tr>
              <td colSpan={4} style={{ textAlign: "center", color: "#77869a", padding: "20px 0" }}>
                No healing actions applied yet
              </td>
            </tr>
          ) : (
            displayedHealing.map((h, idx) => (
              <tr key={`${h.timestamp}-${idx}`}>
                <td>{formatTime(h.timestamp)}</td>
                <td><span className={`badge ${h.anomaly_type}`}>{h.anomaly_type}</span></td>
                <td>{h.action_type}</td>
                <td>{h.mttr_seconds}s</td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      {safeHealing.length > 5 && (
        <div className="timeline-controls" style={{ marginTop: "16px" }}>
          <div className="timeline-slider-info">
            <span>Newest</span>
            <span>Showing {startIndex + 1} - {Math.min(startIndex + 5, safeHealing.length)} of {safeHealing.length}</span>
            <span>Older</span>
          </div>
          <label className="sr-only" htmlFor="healing-slider">Healing Log Slider</label>
          <input
            id="healing-slider"
            type="range"
            min="0"
            max={maxSliderValue}
            value={startIndex}
            onChange={(e) => setStartIndex(parseInt(e.target.value, 10))}
            className="timeline-slider"
            aria-label="Healing History"
          />
        </div>
      )}
    </section>
  );
}
