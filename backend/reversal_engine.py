import json
import re

async def generate_inverse_request(method: str, path: str, request_body_json: str) -> tuple[str, str]:
    """
    Heuristic engine that maps a captured HTTP request to its exact inverse operation 
    using an OpenAPI (Swagger) spec.
    
    Returns a tuple of (inverse_method, inverse_url).
    """
    if not request_body_json:
        print("[REVERSAL ENGINE] No request body to invert.")
        return None, None

    try:
        payload = json.loads(request_body_json)
    except json.JSONDecodeError:
        print("[REVERSAL ENGINE] Invalid JSON payload in trace.")
        return None, None

    # Load the dummy Swagger file
    try:
        with open("backend/dummy_crm_swagger.json", "r") as f:
            swagger = json.load(f)
    except Exception as e:
        print(f"[REVERSAL ENGINE] Could not load Swagger schema: {e}")
        return None, None

    inverse_method = None
    inverse_path_template = None

    # Heuristic Rule 1: Inverse of POST to a collection is DELETE to the item
    if method.upper() == "POST":
        # Look for a companion DELETE route in the schema (e.g. /api/crm/users/{user_id})
        for swagger_path, operations in swagger.get("paths", {}).items():
            if "delete" in map(str.lower, operations.keys()):
                # Does this DELETE path look like the POST path plus a parameter?
                # e.g. path = /api/crm/users, swagger_path = /api/crm/users/{user_id}
                if swagger_path.startswith(path + "/{"):
                    inverse_method = "DELETE"
                    inverse_path_template = swagger_path
                    break

    if not inverse_method or not inverse_path_template:
        print(f"[REVERSAL ENGINE] No heuristic inverse found for {method} {path}")
        return None, None

    # Extract the necessary path parameter from the original POST payload
    # The Swagger path template look like /api/crm/users/{user_id}
    # We need to find "user_id" in the JSON payload
    match = re.search(r"\{([^}]+)\}", inverse_path_template)
    if match:
        param_name = match.group(1)
        if param_name in payload:
            param_value = str(payload[param_name])
            # Construct the final inverse URL
            inverse_path = inverse_path_template.replace(f"{{{param_name}}}", param_value)
            inverse_url = f"http://localhost:8000{inverse_path}"
            return inverse_method, inverse_url
        else:
            print(f"[REVERSAL ENGINE] Could not find required parameter '{param_name}' in payload.")
            return None, None
    
    return None, None
