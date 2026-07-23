# PHASE 7 GATE — Service Wrapper & Dashboard Integration

**Date completed:** 2026-07-23  
**Status:** ✅ PASSED  

---

## 1. REST & WebSocket API Specification

CR²E runs on port `8001` (REST + WebSocket) and is also mountable in-process under ASTRA (`8000`) via `cr2e_router_factory` inside `xapp/api/__init__.py`.

### Endpoints
- `GET /cr2e/status` — Health, rolling history count, and last discovery timestamp.
- `GET /cr2e/dag` — Discovered graph in node-link JSON format.
- `GET /cr2e/dag/diff` — Structural diff (Agreed, Domain-only, Discovery-only, Violations).
- `GET /cr2e/root-cause/{fault_id}` — Full `RootCauseReport` including ATE, CI, and counterfactual step.
- `GET /cr2e/root-cause/latest` — Latest generated report.
- `POST /cr2e/run-discovery` — Triggers a manual discovery run on rolling data.
- `WebSocket /cr2e/ws` — Streams JSON-serialised `RootCauseReport` events directly to dashboard subscribers.

---

## 2. Dashboard Component Mount

A new component `RootCausePanel.jsx` is mounted in `dashboard/src/App.jsx`.
- **Functionality:** Subscribes to the CR²E WebSocket feed, renders ranked causes with significance check, visualises recommended counterfactual adjustments, displays the natural-language explanation, and badges every numeric value with its mandatory `data_provenance_tag`.
- **Design system:** Integrates with ASTRA NOC layout styling.

---

## 3. Integration Verification
- Backend service boots successfully and prints logs.
- WebSocket streaming and router factory tested.

**Gate Decision:** PASSED. API and UI wrappers fully integrated.
