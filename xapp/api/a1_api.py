from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import os
import logging

log = logging.getLogger("astra.a1")
router = APIRouter()

class PolicyContent(BaseModel):
    anomaly_threshold_sigma: float = None
    dt_approval_threshold: float = None
    max_admission_control_drop_pct: int = None
    enforce_blast_radius_limits: bool = True

class A1Policy(BaseModel):
    policyTypeId: str
    policyInstanceId: str
    policyContent: PolicyContent

# A simple simulated A1-P REST Mediator
# In production, this would receive JSON policies from the Non-RT RIC.
active_policies = {}

def get_api_key(api_key: str = None):
    # In prod mode, this simulates MTLS / strict Auth
    if os.getenv("ASTRA_MODE") == "prod":
        expected_key = os.getenv("A1_API_KEY", "astra-secret-token")
        if api_key != expected_key:
            raise HTTPException(status_code=401, detail="Unauthorized - Invalid API Key for A1 Interface")
    return api_key

@router.put("/A1-P/v2/policies/{policyTypeId}/instances/{policyInstanceId}")
async def create_or_update_policy(
    policyTypeId: str,
    policyInstanceId: str,
    policy: A1Policy,
    api_key: str = Depends(get_api_key)
):
    """
    Standard A1-P interface endpoint.
    Accepts intent-based policies from the Non-RT RIC to dynamically constrain the xApp.
    """
    log.info(f"Received A1 Policy [{policyTypeId}/{policyInstanceId}]: {policy.policyContent}")
    
    # Store policy
    key = f"{policyTypeId}:{policyInstanceId}"
    active_policies[key] = policy
    
    # Apply constraints (simulate dynamic intent update)
    if policy.policyContent.anomaly_threshold_sigma is not None:
        os.environ["ANOMALY_THRESHOLD_SIGMA"] = str(policy.policyContent.anomaly_threshold_sigma)
        
    return {"status": "Enforced", "policyId": policyInstanceId}

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
