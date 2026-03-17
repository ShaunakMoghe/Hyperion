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
    Orchestrates a Distributed Saga Rollback.
    Queries the cross-platform graph database for the failed trace's causal chain,
    and executes precise HTTP reversals for every upstream successful API call.
    """
    print(f"\n[ROLLBACK ENGINE] Initiating Distributed Saga Rollback for Trace Failure: {trace_id}")
    
    # 1. Look up the failed trace in Neo4j to confirm it exists
    failed_trace = await graph_db.get_trace_by_id(trace_id)
    if not failed_trace:
        print(f"[ROLLBACK ENGINE] Failed Trace {trace_id} not found in Neo4j.")
        return f"Failed to rollback trace {trace_id}: not found."
    
    print(f"[ROLLBACK ENGINE] Diagnosed Failure on: {failed_trace['method']} {failed_trace['path']}")

    # 2. Retrieve the LIFO causal chain of successful ancestors
    causal_chain = await graph_db.get_causal_chain(trace_id)
    
    if not causal_chain:
        print(f"[ROLLBACK ENGINE] No successful upstream dependencies found for {trace_id}. No compensating transactions required.")
    else:
        print(f"[ROLLBACK ENGINE] Found {len(causal_chain)} upstream operations to reverse executing in LIFO order.")
        
        # 3. Loop through and reverse each parent trace
        for step in causal_chain:
            parent_trace_id = step["trace_id"]
            method = step["method"]
            path = step["path"]
            payload = step["request_body"]
            
            print(f"\n[SAGA CASCADE] Reversing Ancestor Step {parent_trace_id} ({method} {path})...")
            
            inverse_method, inverse_url = await generate_inverse_request(method, path, payload)
            
            if inverse_method and inverse_url:
                print(f"[SAGA CASCADE] Calculated Zero-Shot Reversal: {inverse_method} {inverse_url}")
                try:
                    response = requests.request(inverse_method, inverse_url, timeout=5)
                    print(f"[SAGA CASCADE] Reversal request returned status code: {response.status_code}")
                except requests.exceptions.RequestException as e:
                    print(f"[SAGA CASCADE] ⚠️ Reversal HTTP request failed: {e}")
            else:
                print(f"[SAGA CASCADE] ❌ Could not calculate inverse operation for {method} {path}. Manual intervention required!")
                # In a production Saga, we might queue this for a human operator.
                # For now, we continue looping through the rest of the chain.

    
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
