import requests

PROXY_URL = "http://localhost:8000/api/agent/action?simulate=true"

def run_shadow_agent():
    print("🤖 Shadow Agent: Attempting dry-run...")
    
    # Tool Call 1: Research Data (Safe)
    print("\n🤖 Shadow Agent: Executing Tool 1 - Research CRM Data...")
    res1 = requests.post(
        PROXY_URL, 
        json={"type": "READ_CRM", "query": "fetch_vp_data"}
    )
    trace_id_1 = res1.headers.get("x-trace-id") 
    print(f"✅ Tool 1 Result: {res1.json()} | Trace ID: {trace_id_1}")

    # Tool Call 2: Delete Inbox (Dangerous)
    print("\n🤖 Shadow Agent: Executing Tool 2 - Hallucinated dangerous command...")
    res2 = requests.post(
        PROXY_URL, 
        json={"type": "DANGEROUS_ACTION", "query": "delete_inbox"},
        headers={"x-parent-trace-id": trace_id_1} if trace_id_1 else {}
    )
    print(f"🚨 Tool 2 Result: {res2.status_code} - {res2.json() if res2.status_code == 200 else res2.text}")

if __name__ == "__main__":
    run_shadow_agent()
