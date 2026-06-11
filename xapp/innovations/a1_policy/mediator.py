import logging
from xapp.state import LiveState

log = logging.getLogger("astra.a1_policy")

class A1PolicyMediator:
    """
    Handles A1-P messages from the Non-RT RIC (SMO).
    Registers policy types and handles instances.
    """
    def __init__(self, state: LiveState):
        self.state = state
        self.registered_types = ["astra.threshold.v1", "astra.model.v1"]
        log.info(f"[A1] Initialized A1 Policy Mediator. Registered types: {self.registered_types}")

    def apply_policy(self, policy_type_id: str, policy_instance_id: str, payload: dict) -> dict:
        if policy_type_id not in self.registered_types:
            log.warning(f"[A1] Unknown policy type: {policy_type_id}")
            return {"status": "ERROR", "reason": "Unknown policy type"}

        log.info(f"[A1] Applying policy {policy_type_id} instance {policy_instance_id}: {payload}")

        if policy_type_id == "astra.threshold.v1":
            threshold = payload.get("threshold")
            if threshold is not None:
                with self.state.lock:
                    self.state.threshold = float(threshold)
                log.info(f"[A1] Updated global threshold to {threshold}")
                return {"status": "SUCCESS"}
        
        elif policy_type_id == "astra.model.v1":
            model_version = payload.get("model_version")
            if model_version:
                # In Phase 4, this triggers MLflow model hot-swap
                log.info(f"[A1] Scheduled model swap to version {model_version}")
                return {"status": "SUCCESS", "message": f"Model {model_version} swap scheduled"}

        return {"status": "ERROR", "reason": "Invalid payload"}

    def delete_policy(self, policy_type_id: str, policy_instance_id: str) -> dict:
        log.info(f"[A1] Deleted policy instance {policy_instance_id} of type {policy_type_id}")
        return {"status": "SUCCESS"}
