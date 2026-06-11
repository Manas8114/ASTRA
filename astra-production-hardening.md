# ASTRA Production Hardening Plan

This plan transforms ASTRA from a hackathon prototype to a lab-ready O-RAN xApp.

## Phase 0: Socratic Gate & Open Questions
1. **Token Optimization**: Would you like me to run `pip install code-review-graph` to build a local map and optimize token usage?
2. **Infrastructure Trade-off**: For Phase 3 (Redis/PostgreSQL), should we assume local Docker-compose/Minikube for initial development, or configure the Helm charts for a managed external DB right away?
3. **Edge Case Handling**: For Phase 2 (E2 RC Client), what should the system do if the connection to the RIC drops midway through a healing/slicing action?
4. **Target Environment**: Are we targeting `e2sim` for local testing first, or do you have a live O-RAN testbed ready for immediate integration?

## Proposed Changes & Task Breakdown

### Project Type: BACKEND (DevSecOps)

#### Phase 1: Infrastructure & Deployment
- **Agent**: `devops-engineer` / `orchestrator`
- **Task**: Create `helm/astra-xapp/` and GitHub Actions pipeline.
- **INPUT**: `Dockerfile` and `REMEDIATION_PLAN.md` -> **OUTPUT**: Complete Helm chart and `.github/workflows` -> **VERIFY**: `helm lint` and `helm template` succeed.

#### Phase 2: O-RAN Integration
- **Agent**: `backend-specialist`
- **Task**: Implement real `E2RCClient` with `ricxappframe` and A1 mediator for policy updates.
- **INPUT**: Existing mocks (`e2_rc_client.py`) -> **OUTPUT**: Functional E2 subscription/control message handlers -> **VERIFY**: Unit tests with `e2sim` mocks passing.

#### Phase 3: Persistence & State
- **Agent**: `database-architect`
- **Task**: Refactor in-memory `LiveState` to use Redis, and add PG audit trail via SQLAlchemy.
- **INPUT**: `xapp/state.py` -> **OUTPUT**: `xapp/persistence/redis_client.py` and `audit.py` -> **VERIFY**: Data survives `docker restart` or `kubectl delete pod`.

#### Phase 4: Model Governance & Security
- **Agent**: `backend-specialist` / `security-auditor`
- **Task**: Integrate MLflow, Continual Learning (EWC), and mTLS/OAuth2.
- **INPUT**: Existing training scripts -> **OUTPUT**: MLflow tracking + RBAC/mTLS -> **VERIFY**: `security_scan.py` passes, MLflow registry logs models.

## ✅ Phase X: Final Verification Plan
- [ ] Run `python .agents/scripts/checklist.py .`
- [ ] Run `python .agents/skills/vulnerability-scanner/scripts/security_scan.py .`
- [ ] Validate no purple/violet hex codes in UI components.
- [ ] Ensure all tasks in `astra-production-hardening.md` are marked complete `[x]`.
