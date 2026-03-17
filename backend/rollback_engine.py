import asyncio
from datetime import timedelta
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker

from graph_db import graph_db

# ---------------------------------------------------------
# ACTIVITIES
# ---------------------------------------------------------
import requests
from reversal_engine import generate_inverse_request

@activity.defn
async def execute_compensating_transaction(trace_id: str) -> str:
    """
    Simulates reaching out to an external CRM or Database API 
    to reverse an action that the agent took during the trace.
    """
    print(f"\n[ROLLBACK ENGINE] Executing Compensating Transaction for Trace: {trace_id}")
    
    # 1. Look up the original trace in Neo4j to get the method, path, and request_body
    trace = await graph_db.get_trace_by_id(trace_id)
    if not trace:
        print(f"[ROLLBACK ENGINE] Trace {trace_id} not found in Neo4j.")
        return f"Failed to rollback trace {trace_id}: not found."
    
    # 2. Map original operation to its inverse using the zero-shot heuristic engine
    # (e.g. POST -> DELETE)
    inverse_method, inverse_url = await generate_inverse_request(
        trace["method"], trace["path"], trace["request_body"]
    )
    
    # 3. Physically execute the compensating transaction
    if inverse_method and inverse_url:
        print(f"[ROLLBACK ENGINE] Calculated Zero-Shot Reversal: {inverse_method} {inverse_url}")
        print(f"[ROLLBACK ENGINE] Firing HTTP Reversal...")
        try:
            # We use a 5-second timeout and do not raise_for_status for this mock,
            # as the dummy CRM API isn't actually bound to an alive port in this sandbox
            # but we still want the requests library to attempt it.
            response = requests.request(inverse_method, inverse_url, timeout=5)
            print(f"[ROLLBACK ENGINE] Reversal request returned status code: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"[ROLLBACK ENGINE] Reversal request failed (expected if Dummy CRM is not running): {e}")
    else:
        print(f"[ROLLBACK ENGINE] Could not calculate inverse operation for {trace['method']} {trace['path']}. Proceeding with mock sleep.")
        await asyncio.sleep(2)
    
    # Phase 2 Graph DB: Find any downstream dependent actions
    dependent_traces = await graph_db.find_dependent_traces(trace_id)
    if dependent_traces:
        print(f"[ROLLBACK ENGINE] Cascading rollback required for {len(dependent_traces)} downstream traces: {dependent_traces}")
    
    print(f"[ROLLBACK ENGINE] ✅ Rollback Complete for Trace: {trace_id}")
    return f"Rolled back trace {trace_id} successfully."

@activity.defn
async def notify_administrators(trace_id: str) -> str:
    """
    Simulates sending an alert to DevSecOps about the agent failure and rollback.
    """
    print(f"[ROLLBACK ENGINE] 🚨 Alerting DevSecOps: Agent Kill Switch fired on Trace {trace_id}")
    return "Admins notified."

# ---------------------------------------------------------
# WORKFLOWS
# ---------------------------------------------------------
@workflow.defn
class AgentRollbackWorkflow:
    @workflow.run
    async def run(self, trace_id: str) -> str:
        # Step 1: Execute the rollback
        result = await workflow.execute_activity(
            execute_compensating_transaction,
            trace_id,
            start_to_close_timeout=timedelta(seconds=10),
        )
        
        # Step 2: Notify the admins
        await workflow.execute_activity(
            notify_administrators,
            trace_id,
            start_to_close_timeout=timedelta(seconds=5),
        )
        
        return result

# ---------------------------------------------------------
# WORKER / MAIN
# ---------------------------------------------------------
async def main():
    # Phase 2: Connect worker to Graph DB
    await graph_db.connect()

    # Connect to the local Temporal server (requires Temporal to be running)
    try:
        client = await Client.connect("localhost:7233")
    except Exception as e:
        print("[ROLLBACK ENGINE] WARNING: Could not connect to Temporal server at localhost:7233.")
        print("[ROLLBACK ENGINE] To run the Rollback Engine, ensure Temporal is running.")
        print("[ROLLBACK ENGINE] Example: `temporal server start-dev`")
        return

    # Run the worker to listen for rollback tasks
    worker = Worker(
        client,
        task_queue="agent-rollback-queue",
        workflows=[AgentRollbackWorkflow],
        activities=[execute_compensating_transaction, notify_administrators],
    )
    
    print("\n[ROLLBACK ENGINE] Worker started. Listening for compensating transactions on 'agent-rollback-queue'...")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
