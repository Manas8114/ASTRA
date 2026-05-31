import { Cpu } from "lucide-react";

export function DTSimView({ simulation }) {
  const improvement = simulation ? Math.round(simulation.improvement_pct * 100) : 0;
  return (
    <section className="panel">
      <div className="panel-title"><Cpu size={18} /> Digital Twin</div>
      {!simulation && <div className="empty">Awaiting twin simulation</div>}
      {simulation && (
        <>
          <div className={`approval ${simulation.approved ? "ok" : "bad"}`}>
            {simulation.approved ? "APPROVED" : "ESCALATING"} · {improvement}% improvement
          </div>
          <div className="state-pair">
            <State title="Current" data={simulation.current_state} />
            <State title="Projected" data={simulation.projected_state} />
          </div>
        </>
      )}
    </section>
  );
}

function State({ title, data }) {
  return (
    <div className="state-box">
      <h3>{title}</h3>
      {Object.entries(data || {}).slice(0, 6).map(([key, value]) => (
        <div className="kv" key={key}><span>{key}</span><strong>{Number(value).toFixed(1)}</strong></div>
      ))}
    </div>
  );
}
