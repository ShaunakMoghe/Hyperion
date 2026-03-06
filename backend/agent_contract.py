import yaml
from fastapi import HTTPException

def load_contract():
    try:
        with open("agent_contract.yaml", "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[CONTRACT] Failed to load agent_contract.yaml: {e}")
        return None

def validate_action_against_contract(action: dict):
    contract = load_contract()
    if not contract:
        return # Fail-open or Fail-closed depending on policy. We'll allow it if no contract for MVP.
    
    action_type = action.get("type", "").upper()
    
    # Check explicitly forbidden actions (Kill Switch)
    forbidden = [f.get("action_type") for f in contract.get("permissions", {}).get("forbidden_actions", [])]
    if action_type in forbidden:
        print(f"[CONTRACT] 🛑 VIOLATION: Agent attempted forbidden action '{action_type}'.")
        raise HTTPException(status_code=403, detail=f"Action '{action_type}' blocked by Agent Contract.")

    # Check allowed list
    allowed = [a.get("action_type") for a in contract.get("permissions", {}).get("allowed_actions", [])]
    if action_type not in allowed:
         print(f"[CONTRACT] ⚠️ WARNING: Agent attempted unlisted action '{action_type}'.")
         raise HTTPException(status_code=403, detail=f"Action '{action_type}' is not in the allowed Agent Contract.")
    
    print(f"[CONTRACT] ✅ Action '{action_type}' approved by contract.")
    return True
