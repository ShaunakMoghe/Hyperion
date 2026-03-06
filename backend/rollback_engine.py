import asyncio
from datetime import timedelta
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker

# ---------------------------------------------------------
# ACTIVITIES
# ---------------------------------------------------------
@activity.defn
async def execute_compensating_transaction(trace_id: str) -> str:
    """
    Simulates reaching out to an external CRM or Database API 
    to reverse an action that the agent took during the trace.
    """
    print(f"\n[ROLLBACK ENGINE] Executing Compensating Transaction for Trace: {trace_id}")
    await asyncio.sleep(2) # Simulate network call
    
    # In a real system, this would lookup the trace, extract the original request,
    # and map it to the inverse operation (e.g. DELETE if the original was POST).
    
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
