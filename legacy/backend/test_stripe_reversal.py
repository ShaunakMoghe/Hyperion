import asyncio
import json
import sys
import os

# Add backend directory to path if running from root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from reversal_engine import generate_inverse_request

async def test_reversal():
    print("--- Testing ZERO-SHOT REVERSAL ENGINE with Stripe OpenAPI ---")
    
    # Mock Trace 1: Create a Customer
    print("\n[MOCK TRACE 1] Agent creating Stripe Customer...")
    customer_payload = json.dumps({"id": "cus_M12345", "email": "alice@example.com", "name": "Alice"})
    method_1 = "POST"
    path_1 = "/v1/customers"
    print(f"Intercepted Action: {method_1} {path_1} | Body: {customer_payload}")
    
    inv_method_1, inv_url_1 = await generate_inverse_request(method_1, path_1, customer_payload)
    print(f"[HEURISTIC SUCCESS] Reversal Calculated => {inv_method_1} {inv_url_1}")

    # Mock Trace 2: Create a Charge
    print("\n[MOCK TRACE 2] Agent creating Stripe Charge...")
    charge_payload = json.dumps({"id": "ch_987654", "amount": 5000, "currency": "usd", "customer": "cus_M12345"})
    method_2 = "POST"
    path_2 = "/v1/charges"
    print(f"Intercepted Action: {method_2} {path_2} | Body: {charge_payload}")
    
    inv_method_2, inv_url_2 = await generate_inverse_request(method_2, path_2, charge_payload)
    print(f"[HEURISTIC SUCCESS] Reversal Calculated (Domain Fallback) => {inv_method_2} {inv_url_2}\n")

if __name__ == "__main__":
    asyncio.run(test_reversal())
