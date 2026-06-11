import React, { useState, useEffect } from "react";
import { Sliders, Zap } from "lucide-react";

export function NocControls() {
  const [threshold, setThreshold] = useState("");
  const [statusMsg, setStatusMsg] = useState("");
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    fetch("http://localhost:8000/status")
      .then((res) => res.json())
      .then((data) => {
        if (data.threshold !== undefined) {
          setThreshold(data.threshold.toFixed(4));
        }
      })
      .catch(() => {});
  }, []);

  const handleUpdatePolicy = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch("http://localhost:8000/policy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threshold: parseFloat(threshold) })
      });
      const data = await res.json();
      if (data.accepted) {
        setThreshold(data.threshold.toFixed(4));
        showStatus("Policy threshold updated successfully!", false);
      } else {
        showStatus("Failed to update policy threshold.", true);
      }
    } catch {
      showStatus("Network error updating policy.", true);
    }
  };

  const handleInject = async (type) => {
    try {
      const res = await fetch(`http://localhost:8000/inject/${type}`, {
        method: "POST"
      });
      if (res.ok) {
        showStatus(`Successfully injected ${type} anomaly!`, false);
      } else {
        showStatus(`Failed to inject ${type} anomaly.`, true);
      }
    } catch {
      showStatus("Network error triggering anomaly injection.", true);
    }
  };

  const showStatus = (msg, err) => {
    setStatusMsg(msg);
    setIsError(err);
    setTimeout(() => {
      setStatusMsg("");
    }, 4000);
  };

  return (
    <section className="panel">
      <div className="panel-title"><Sliders size={18} /> NOC Control Panel</div>
      
      {statusMsg && (
        <div style={{
          padding: "8px 12px",
          borderRadius: "6px",
          fontSize: "12px",
          marginBottom: "12px",
          background: isError ? "rgba(227, 93, 93, 0.15)" : "rgba(69, 179, 107, 0.15)",
          color: isError ? "#ff8383" : "#7ee09d",
          border: isError ? "1px solid rgba(227, 93, 93, 0.3)" : "1px solid rgba(69, 179, 107, 0.3)"
        }}>
          {statusMsg}
        </div>
      )}

      <div style={{ marginBottom: "16px" }}>
        <h4 style={{ margin: "0 0 8px 0", fontSize: "13px", color: "#c7d2df" }}>Adjust Detection Threshold</h4>
        <form onSubmit={handleUpdatePolicy} style={{ display: "flex", gap: "8px" }}>
          <label className="sr-only" htmlFor="threshold-input">Threshold Value</label>
          <input
            id="threshold-input"
            type="number"
            step="0.0001"
            min="0.0001"
            max="1.0"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
            aria-label="Threshold Value"
            style={{
              flex: 1,
              background: "#0d131d",
              border: "1px solid #202b3a",
              borderRadius: "6px",
              padding: "6px 10px",
              color: "#edf2f7",
              outline: "none"
            }}
          />
          <button type="submit" style={{
            background: "#182235",
            color: "#38bdf8",
            border: "1px solid #2d3b52",
            borderRadius: "6px",
            padding: "6px 12px",
            fontSize: "12px",
            fontWeight: "bold",
            cursor: "pointer"
          }}>
            Apply
          </button>
        </form>
      </div>

      <div>
        <h4 style={{ margin: "0 0 8px 0", fontSize: "13px", color: "#c7d2df" }}>Trigger Anomaly Simulation</h4>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
          {["CONGESTION", "HIGH_LATENCY", "PACKET_LOSS", "SLICE_OVERFLOW"].map((type) => (
            <button
              key={type}
              onClick={() => handleInject(type)}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "6px",
                background: "#0d131d",
                border: "1px solid #202b3a",
                borderRadius: "6px",
                padding: "8px",
                color: "#edf2f7",
                fontSize: "11px",
                cursor: "pointer",
                transition: "all 0.2s ease"
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "#38bdf8";
                e.currentTarget.style.background = "#101b2b";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "#202b3a";
                e.currentTarget.style.background = "#0d131d";
              }}
            >
              <Zap size={12} style={{ color: "#ffb86b" }} />
              {type.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
