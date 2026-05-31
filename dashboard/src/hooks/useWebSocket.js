import { useEffect, useMemo, useState } from "react";

const initial = {
  connected: false,
  kpis: [],
  anomalies: [],
  healing: [],
  simulation: null,
  attribution: null,
  events: [],
  lastMessage: null
};

export function useWebSocket(url = "ws://localhost:8000/ws") {
  const [state, setState] = useState(initial);

  useEffect(() => {
    const ws = new WebSocket(url);
    ws.onopen = () => setState((s) => ({ ...s, connected: true }));
    ws.onclose = () => setState((s) => ({ ...s, connected: false }));
    ws.onmessage = (message) => {
      const event = JSON.parse(message.data);
      setState((s) => {
        const events = [event, ...s.events].slice(0, 120);
        const base = { ...s, events, lastMessage: message.data };
        if (event.type === "KPI_UPDATE") {
          return {
            ...base,
            kpis: [...s.kpis, { timestamp: event.timestamp, ...event.kpis }].slice(-60)
          };
        }
        if (event.type === "ANOMALY_DETECTED") {
          return {
            ...base,
            anomalies: [event, ...s.anomalies].slice(0, 30),
            attribution: event
          };
        }
        if (event.type === "DT_SIMULATION") {
          return { ...base, simulation: event };
        }
        if (event.type === "HEALING_APPLIED") {
          return { ...base, healing: [event, ...s.healing].slice(0, 30) };
        }
        return base;
      });
    };
    return () => ws.close();
  }, [url]);

  return useMemo(() => state, [state]);
}
