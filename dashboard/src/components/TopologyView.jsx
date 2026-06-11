import React, { useState, useEffect } from "react";
import { Network, Server, X } from "lucide-react";

const CELLS = [
  { id: "cell_001", x: 200, y: 150, type: "macro" }, // Center
  { id: "cell_002", x: 200, y: 30, type: "small" }, // Top
  { id: "cell_003", x: 320, y: 220, type: "small" }, // Bottom Right
  { id: "cell_004", x: 80, y: 220, type: "small" } // Bottom Left
];

const LINKS = [
  { source: "cell_001", target: "cell_002" },
  { source: "cell_001", target: "cell_003" },
  { source: "cell_001", target: "cell_004" },
  { source: "cell_003", target: "cell_004" } // Edge link
];

const getLatestKPIs = (kpis) => {
  if (!kpis || kpis.length === 0) return null;
  return kpis[kpis.length - 1];
};

export function TopologyView({ events, kpis, simulation }) {
  const [selectedCell, setSelectedCell] = useState(null);
  const [animatingLinks, setAnimatingLinks] = useState([]);
  
  const [cellStatus, setCellStatus] = useState({
    cell_001: "normal",
    cell_002: "normal",
    cell_003: "normal",
    cell_004: "normal"
  });

  const latestEvent = events.length > 0 ? events[events.length - 1] : null;
  const latestKPIs = getLatestKPIs(kpis);

  useEffect(() => {
    if (!latestEvent) return;
    
    // Fallback to cell_001 if the event doesn't specify a source cell
    const targetCell = latestEvent.source_cell || "cell_001";
    
    if (latestEvent.type === "ANOMALY_DETECTED") {
      setCellStatus(prev => ({ ...prev, [targetCell]: "anomalous" }));
    } else if (latestEvent.type === "HEALING_APPLIED") {
      setCellStatus(prev => ({ ...prev, [targetCell]: "healing" }));
      triggerBroadcastAnimation(targetCell);
      
      // Auto reset to normal after 5 seconds
      setTimeout(() => {
        setCellStatus(prev => ({ ...prev, [targetCell]: "normal" }));
      }, 5000);
    } else if (latestEvent.type === "MULTICELL_BROADCAST") {
      triggerBroadcastAnimation(targetCell);
    }
  }, [events]);

  const triggerBroadcastAnimation = (sourceNodeId) => {
    const activeLinks = LINKS.filter(l => l.source === sourceNodeId || l.target === sourceNodeId)
      .map(l => `${l.source}-${l.target}`);
    
    setAnimatingLinks(activeLinks);
    
    setTimeout(() => {
      setAnimatingLinks([]);
    }, 2000);
  };

  const getNodeColor = (status) => {
    switch(status) {
      case "anomalous": return "#e35d5d";
      case "healing": return "#38bdf8";
      default: return "#45b36b";
    }
  };

  const renderCellInspector = () => {
    if (!selectedCell) return null;
    const status = cellStatus[selectedCell.id];
    
    return (
      <div className="cell-inspector">
        <div className="inspector-header">
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <Server size={16} />
            <strong>{selectedCell.id}</strong>
          </div>
          <button className="close-btn" onClick={() => setSelectedCell(null)} aria-label="Close Inspector">
            <X size={14} />
          </button>
        </div>
        
        <div className="inspector-status">
          <span className={`status-badge ${status}`}>
            {status.toUpperCase()}
          </span>
          <span className="e2-badge">E2 CONNECTED</span>
        </div>
        
        {latestKPIs && (
          <div className="inspector-kpis">
            <div className="kpi-row">
              <span>DL Throughput</span>
              <strong>{latestKPIs.dl_throughput_mbps?.toFixed(2) || "0.00"} Mbps</strong>
            </div>
            <div className="kpi-row">
              <span>Latency</span>
              <strong>{latestKPIs.latency_ms?.toFixed(2) || "0.00"} ms</strong>
            </div>
            <div className="kpi-row">
              <span>BLER</span>
              <strong>{latestKPIs.bler_pct?.toFixed(2) || "0.00"} %</strong>
            </div>
            <div className="kpi-row">
              <span>RSRP</span>
              <strong>{latestKPIs.rsrp_dbm?.toFixed(2) || "0.00"} dBm</strong>
            </div>
            <div className="kpi-row">
              <span>Handover</span>
              <strong>{latestKPIs.handover_success_rate?.toFixed(2) || "0.00"} %</strong>
            </div>
            <div className="kpi-row">
              <span>Slice Util</span>
              <strong>{latestKPIs.slice_utilisation_pct?.toFixed(2) || "0.00"} %</strong>
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <section className="panel topology-panel">
      <div className="panel-title"><Network size={18} /> Interactive Topology</div>
      
      <div className="topology-container">
        <svg viewBox="0 0 400 300" className="topology-svg">
          <defs>
            {LINKS.map((link) => {
              const source = CELLS.find(c => c.id === link.source);
              const target = CELLS.find(c => c.id === link.target);
              const linkId = `${link.source}-${link.target}`;
              return (
                <path 
                  key={`path-${linkId}`}
                  id={`path-${linkId}`} 
                  d={`M ${source.x} ${source.y} L ${target.x} ${target.y}`} 
                  fill="none" 
                  stroke="none" 
                />
              );
            })}
          </defs>

          {/* Links */}
          {LINKS.map((link, i) => {
            const source = CELLS.find(c => c.id === link.source);
            const target = CELLS.find(c => c.id === link.target);
            const linkId = `${link.source}-${link.target}`;
            const isAnimating = animatingLinks.includes(linkId);
            
            return (
              <g key={`link-${i}`}>
                <line 
                  x1={source.x} y1={source.y} 
                  x2={target.x} y2={target.y} 
                  className="topology-link" 
                />
                {isAnimating && (
                  <circle r="5" fill="#38bdf8" className="packet-anim">
                    <animateMotion dur="0.8s" repeatCount="3">
                      <mpath href={`#path-${linkId}`} />
                    </animateMotion>
                  </circle>
                )}
              </g>
            );
          })}
          
          {/* Nodes */}
          {CELLS.map((cell) => {
            const status = cellStatus[cell.id];
            const color = getNodeColor(status);
            const isSelected = selectedCell?.id === cell.id;
            
            return (
              <g 
                key={cell.id} 
                transform={`translate(${cell.x}, ${cell.y})`} 
                onClick={() => setSelectedCell(cell)}
                className={`topology-node ${isSelected ? "selected" : ""}`}
              >
                {/* Pulse effect for anomalies/healing */}
                {status !== "normal" && (
                  <circle r={cell.type === "macro" ? "24" : "20"} fill={color} className="node-pulse" />
                )}
                
                <circle 
                  r={cell.type === "macro" ? "16" : "12"} 
                  fill="#0d131d" 
                  stroke={color} 
                  strokeWidth="3" 
                  className="node-circle"
                />
                <text y={cell.type === "macro" ? "32" : "26"} textAnchor="middle" className="node-label">
                  {cell.id}
                </text>
              </g>
            );
          })}
        </svg>

        {renderCellInspector()}
      </div>
    </section>
  );
}
