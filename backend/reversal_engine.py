import json
import re

async def generate_inverse_request(method: str, path: str, request_body_json: str) -> tuple[str, str]:
    """
    Advanced Heuristic engine that maps a captured HTTP request to its exact inverse operation 
    using an OpenAPI (Swagger) spec. Supports dynamic ID extraction and domain-specific fallbacks.
    
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

    # Load the Stripe Swagger file, fallback to Dummy if not found
    schema_path = "backend/stripe_openapi.json"
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            swagger = json.load(f)
    except Exception as e:
        print(f"[REVERSAL ENGINE] Could not load {schema_path}, falling back to dummy...")
        try:
            with open("backend/dummy_crm_swagger.json", "r", encoding="utf-8") as f:
                swagger = json.load(f)
        except Exception as e2:
            print(f"[REVERSAL ENGINE] Could not load Swagger schema: {e2}")
            return None, None

    inverse_method = None
    inverse_path_template = None
    fallback_query = ""

    # Dynamic ID Extraction: Look for common primary identifiers
    primary_id = None
    for key in ["id", "customer", "charge", "user_id"]:
        if key in payload:
            primary_id = str(payload[key])
            break

    if not primary_id:
        print("[REVERSAL ENGINE] Could not find a primary identifier (id/customer/charge/user_id) in payload.")
        return None, None

    # Heuristic Rule 1: Semantic Path Matching (Inverse of POST to a collection is DELETE to the item)
    if method.upper() == "POST":
        for swagger_path, operations in swagger.get("paths", {}).items():
            if "delete" in map(str.lower, operations.keys()):
                # Match e.g., /v1/customers mapping to /v1/customers/{customer}
                if swagger_path.startswith(path + "/{"):
                    inverse_method = "DELETE"
                    inverse_path_template = swagger_path
                    break

    # Heuristic Rule 2: Domain-Specific Fallbacks (The Clearinghouse Logic)
    if not inverse_method and method.upper() == "POST":
        if path == "/v1/charges":
            if "/v1/refunds" in swagger.get("paths", {}):
                if "post" in map(str.lower, swagger["paths"]["/v1/refunds"].keys()):
                    inverse_method = "POST"
                    inverse_path_template = "/v1/refunds"
                    fallback_query = f"?charge={primary_id}"

    if not inverse_method or not inverse_path_template:
        print(f"[REVERSAL ENGINE] No heuristic inverse found for {method} {path}")
        return None, None

    # Parameter Replacement in the inverse path
    inverse_path = inverse_path_template
    match = re.search(r"\{([^}]+)\}", inverse_path_template)
    if match:
        param_name = match.group(1)
        inverse_path = inverse_path_template.replace(f"{{{param_name}}}", primary_id)

    inverse_url = f"http://localhost:8000{inverse_path}{fallback_query}"
    return inverse_method, inverse_url
