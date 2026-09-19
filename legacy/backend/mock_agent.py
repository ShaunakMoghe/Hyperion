import requests
import time

PROXY_URL = "http://localhost:8000/api/agent/action"

def run_mock_agent():
    print("🤖 Mock Agent: Waking up to process user request 'Compile a report and email the VP'.")
    
    # Tool Call 1: Research Data (Safe)
    print("\n🤖 Mock Agent: Executing Tool 1 - Research CRM Data...")
    res1 = requests.post(
        PROXY_URL, 
        json={"type": "READ_CRM", "query": "fetch_vp_data"}
    )
    # The proxy returns the trace_id of this action, which we will use as the parent for the next
    # Wait, our proxy doesn't return the trace_id in the response yet. Let's assume it does.
    # We should update main.py to return trace_id. Let's just mock it or assume the response returns it.
    trace_id_1 = res1.headers.get("x-trace-id") 
    print(f"✅ Tool 1 Result: {res1.json()} | Trace ID: {trace_id_1}")

    time.sleep(1)

    # Tool Call 2: Draft the Report (Safe, causally linked to Tool 1)
    print("\n🤖 Mock Agent: Executing Tool 2 - Drafting Report...")
    res2 = requests.post(
        PROXY_URL, 
        json={"type": "WRITE_DOC", "content": "The VP report is ready."},
        headers={"x-parent-trace-id": trace_id_1} if trace_id_1 else {}
    )
    trace_id_2 = res2.headers.get("x-trace-id")
    print(f"✅ Tool 2 Result: {res2.json()} | Trace ID: {trace_id_2}")

    time.sleep(1)

    # Tool Call 3: Delete Inbox (Dangerous, causally linked to Tool 2)
    print("\n🤖 Mock Agent: Executing Tool 3 - Uh oh, hallucinating a destructive command...")
    res3 = requests.post(
        PROXY_URL, 
        json={"type": "DANGEROUS_ACTION", "query": "delete_inbox"},
        headers={"x-parent-trace-id": trace_id_2} if trace_id_2 else {}
    )
    print(f"🚨 Tool 3 Result: {res3.status_code} - {res3.json() if res3.status_code == 200 else res3.text}")
    print("🤖 Mock Agent: Execution halted by Intercept Proxy.")

if __name__ == "__main__":
    run_mock_agent()
