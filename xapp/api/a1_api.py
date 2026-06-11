from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import os
import logging
from xapp.state import StateManager
from xapp.innovations.a1_policy.mediator import A1PolicyMediator

log = logging.getLogger("astra.a1")

class PolicyContent(BaseModel):
    anomaly_threshold_sigma: float = None
    dt_approval_threshold: float = None
    max_admission_control_drop_pct: int = None
    enforce_blast_radius_limits: bool = True
    threshold: float = None
    model_version: str = None

class A1Policy(BaseModel):
    policyTypeId: str
    policyInstanceId: str
    policyContent: PolicyContent

active_policies = {}

def get_api_key(api_key: str = None):
    if os.getenv("ASTRA_MODE") == "prod":
        expected_key = os.getenv("A1_API_KEY", "astra-secret-token")
        if api_key != expected_key:
            raise HTTPException(status_code=401, detail="Unauthorized - Invalid API Key for A1 Interface")
    return api_key

def a1_router(state_manager: StateManager) -> APIRouter:
    router = APIRouter()
    
    def get_state(cell_id: str = None):
        return state_manager.get_state(cell_id or os.getenv("CELL_ID", "cell_001"))

    @router.put("/A1-P/v2/policies/{policyTypeId}/instances/{policyInstanceId}")
    async def create_or_update_policy(
        policyTypeId: str,
        policyInstanceId: str,
        policy: A1Policy,
        api_key: str = Depends(get_api_key),
        cell_id: str = None
    ):
        log.info(f"Received A1 Policy [{policyTypeId}/{policyInstanceId}]: {policy.policyContent}")
        
        state = get_state(cell_id)
        mediator = A1PolicyMediator(state)
        
        key = f"{policyTypeId}:{policyInstanceId}"
        active_policies[key] = policy
        
        payload = policy.policyContent.model_dump(exclude_unset=True)
        result = mediator.apply_policy(policyTypeId, policyInstanceId, payload)
        
        if policy.policyContent.anomaly_threshold_sigma is not None:
            os.environ["ANOMALY_THRESHOLD_SIGMA"] = str(policy.policyContent.anomaly_threshold_sigma)
            
        return {"status": result.get("status", "Enforced"), "policyId": policyInstanceId, "details": result}

    @router.get("/A1-P/v2/policies/{policyTypeId}/instances/{policyInstanceId}")
    async def get_policy(
        policyTypeId: str,
        policyInstanceId: str,
        api_key: str = Depends(get_api_key)
    ):
        key = f"{policyTypeId}:{policyInstanceId}"
        if key not in active_policies:
            raise HTTPException(status_code=404, detail="Policy not found")
        return active_policies[key]
        
    @router.delete("/A1-P/v2/policies/{policyTypeId}/instances/{policyInstanceId}")
    async def delete_policy(
        policyTypeId: str,
        policyInstanceId: str,
        api_key: str = Depends(get_api_key),
        cell_id: str = None
    ):
        key = f"{policyTypeId}:{policyInstanceId}"
        if key in active_policies:
            del active_policies[key]
            state = get_state(cell_id)
            mediator = A1PolicyMediator(state)
            mediator.delete_policy(policyTypeId, policyInstanceId)
        return {"status": "Deleted"}

    return router
