from __future__ import annotations

import asyncio
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from xapp.api.rest_api import rest_router
from xapp.api.websocket_server import WebSocketHub, websocket_router
from xapp.classifier.anomaly_classifier import AnomalyClassifier
from xapp.digital_twin.twin_simulator import DigitalTwinSimulator
from xapp.healing.action_engine import HealingActionEngine
from xapp.ingestion.kpi_buffer import KPIBuffer
from xapp.ingestion.kpi_schema import AnomalyType
from xapp.ingestion.kpi_subscriber import dev_kpi_stream
from xapp.model.anomaly_detector import AnomalyDetector
from xapp.model.attention_extractor import AttentionExtractor
from xapp.state import LiveState


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


async def detection_loop(state: LiveState, hub: WebSocketHub) -> None:
    buffer = KPIBuffer()
    detector = AnomalyDetector(consecutive_trigger=int(os.getenv("CONSECUTIVE_ANOMALY_TRIGGER", "5")))
    state.threshold = detector.threshold
    last_calculated_threshold = detector.threshold
    classifier = AnomalyClassifier()
    attention = AttentionExtractor()
    twin = DigitalTwinSimulator(detector, float(os.getenv("DT_APPROVAL_THRESHOLD", "0.20")))
    healing = HealingActionEngine()
    stream = dev_kpi_stream(state)

    async for kpi in stream:
        buffer.push(kpi)
        kpi_event = state.record_event({"type": "KPI_UPDATE", "kpis": kpi.to_dict()})
        await hub.broadcast(kpi_event)

        window = buffer.get_window()
        if window is not None:
            if abs(state.threshold - last_calculated_threshold) > 1e-6:
                detector.threshold = state.threshold
                detector.min_samples = 99999999
            result = detector.detect(window)
            state.threshold = detector.threshold
            last_calculated_threshold = detector.threshold
            if result.declared:
                classification = classifier.classify(result.per_feature_mse)
                attr = attention.extract(result.attention_weights)
                anomaly_event = state.record_event(
                    {
                        "type": "ANOMALY_DETECTED",
                        "anomaly_type": classification.anomaly_type.value,
                        "confidence": classification.confidence,
                        "top_kpis": classification.top_kpis,
                        "reasoning": classification.reasoning,
                        "attention_weights": attr.weights,
                        "top_cause": attr.top_cause,
                        "explanation": attr.explanation,
                        "total_mse": result.total_mse,
                    }
                )
                await hub.broadcast(anomaly_event)

                candidate = healing.candidate_for(classification.anomaly_type)
                current = buffer.recent_average() or kpi.to_dict()
                if classification.anomaly_type == AnomalyType.NOVEL or candidate is None:
                    event = state.record_event(
                        {
                            "type": "ESCALATION",
                            "reason": "Novel anomaly is never auto-healed.",
                            "anomaly_type": classification.anomaly_type.value,
                        }
                    )
                    await hub.broadcast(event)
                else:
                    sim = twin.simulate_action(candidate, current, result.total_mse)
                    sim_event = state.record_event(
                        {
                            "type": "DT_SIMULATION",
                            "anomaly_type": classification.anomaly_type.value,
                            "action": candidate.action_type,
                            "parameters": candidate.parameters,
                            "current_mse": result.total_mse,
                            "projected_mse": sim.projected_mse,
                            "improvement_pct": sim.improvement_pct,
                            "approved": sim.approved,
                            "current_state": current,
                            "projected_state": sim.projected_state,
                        }
                    )
                    await hub.broadcast(sim_event)
                    if sim.approved:
                        healed = await healing.execute(classification.anomaly_type, candidate, sim, current)
                        event = state.record_event(healed)
                        with state.lock:
                            state.injected_anomaly = None
                    else:
                        event = state.record_event(
                            {
                                "type": "ESCALATION",
                                "reason": sim.recommendation,
                                "anomaly_type": classification.anomaly_type.value,
                            }
                        )
                    await hub.broadcast(event)
        await asyncio.sleep(1)


async def main() -> None:
    load_dotenv()
    if os.getenv("DEV_MODE", "false").lower() != "true":
        raise RuntimeError("No production E2 KPI source configured. Set DEV_MODE=true for local simulation.")

    state = LiveState(cell_id=os.getenv("CELL_ID", "cell_001"))
    hub = WebSocketHub()
    app = FastAPI(title="ASTRA xApp")
    
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(rest_router(state))
    app.include_router(websocket_router(hub))

    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("ASTRA_API_PORT", "8000")), log_level="info")
    server = uvicorn.Server(config)
    loop_task = asyncio.create_task(detection_loop(state, hub))
    server_task = asyncio.create_task(server.serve())
    print(f"ASTRA xApp running. Cell ID: {state.cell_id}. Threshold: {state.threshold:.4f}")
    await asyncio.gather(loop_task, server_task)


if __name__ == "__main__":
    asyncio.run(main())
