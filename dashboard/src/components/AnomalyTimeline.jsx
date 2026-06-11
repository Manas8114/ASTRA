import { useState, useEffect } from "react";
import { AlertTriangle } from "lucide-react";

export function AnomalyTimeline({ anomalies }) {
  const [startIndex, setStartIndex] = useState(0);

  // Auto reset to newest (index 0) when a new anomaly is detected
  useEffect(() => {
    setStartIndex(0);
  }, [anomalies.length]);

  const displayedAnomalies = anomalies.slice(startIndex, startIndex + 5);
  const maxSliderValue = Math.max(0, anomalies.length - 5);

  return (
    <section className="panel">
      <div className="panel-title"><AlertTriangle size={18} /> Anomaly Timeline</div>
      <div className="timeline">
        {anomalies.length === 0 && <div className="empty">Waiting for declared anomalies</div>}
        {displayedAnomalies.map((event, idx) => (
          <div className="event-row" key={`${event.timestamp}-${startIndex + idx}`}>
            <span className={`badge ${event.anomaly_type}`}>{event.anomaly_type}</span>
            <strong>{Math.round(event.confidence * 100)}%</strong>
            <span>{event.top_kpis?.[0] || "Unknown"}</span>
          </div>
        ))}
      </div>
      
      {anomalies.length > 5 && (
        <div className="timeline-controls">
          <div className="timeline-slider-info">
            <span>Newest</span>
            <span>Showing {startIndex + 1} - {Math.min(startIndex + 5, anomalies.length)} of {anomalies.length}</span>
            <span>Older</span>
          </div>
          <label className="sr-only" htmlFor="timeline-slider">Anomaly Timeline Slider</label>
          <input
            id="timeline-slider"
            type="range"
            min="0"
            max={maxSliderValue}
            value={startIndex}
            onChange={(e) => setStartIndex(parseInt(e.target.value, 10))}
            className="timeline-slider"
            aria-label="Timeline History"
          />
        </div>
      )}
    </section>
  );
}
