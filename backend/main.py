from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import time
import uuid
import asyncio
from temporalio.client import Client

app = FastAPI(title="State-as-a-Service Agent Intercept Proxy")

# Allow Next.js dashboard to interact
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for execution traces (simulating Pinecone/Neo4j/ClickHouse)
execution_traces = []

async def trigger_rollback_workflow(trace_id: str):
    """
    Connects to Temporal and kicks off the compensating transaction workflow.
    Falls back to a local async simulation if Temporal is not running.
    """
    # Find trace and mark it as rolling back
    trace_idx = next((i for i, t in enumerate(execution_traces) if t["trace_id"] == trace_id), -1)
    if trace_idx != -1:
        execution_traces[trace_idx]["rollback_status"] = "in_progress"

    try:
        client = await Client.connect("localhost:7233")
        await client.execute_workflow(
            "AgentRollbackWorkflow",
            trace_id,
            id=f"rollback-{trace_id}",
            task_queue="agent-rollback-queue",
        )
        print(f"[KILL SWITCH] Rollback Workflow initiated for Trace {trace_id} via Temporal")
        if trace_idx != -1:
             execution_traces[trace_idx]["rollback_status"] = "completed"
    except Exception as e:
        print(f"[KILL SWITCH] Temporal not available, falling back to local simulation for {trace_id}")
        await asyncio.sleep(2) # Simulate network call to CRM
        print(f"[ROLLBACK ENGINE] Executing Compensating Transaction for Trace: {trace_id}")
        await asyncio.sleep(1)
        print(f"[ROLLBACK ENGINE] ✅ Rollback Complete for Trace: {trace_id}")
        if trace_idx != -1:
             execution_traces[trace_idx]["rollback_status"] = "completed"

@app.middleware("http")
async def mcp_intercept_middleware(request: Request, call_next):    
    # Skip non-agent routes (like UI telemetry routes) and CORS OPTIONS requests
    if not request.url.path.startswith("/api/agent") or request.method == "OPTIONS":
        return await call_next(request)

    # 1. State Snapshot: Capture intent before agent logic runs
    trace_id = str(uuid.uuid4())
    start_time = time.time()
    
    body = b""
    if request.method in ("POST", "PUT", "PATCH"):
         body = await request.body()
    
    # State capture mapping
    trace = {
        "trace_id": trace_id,
        "path": request.url.path,
        "method": request.method,
        "request_body": body.decode('utf-8') if body else None,
        "timestamp": start_time,
        "status": "pending_execution"
    }
    execution_traces.append(trace)
    print(f"[INTERCEPT] Captured state for {request.method} {request.url.path} (Trace: {trace_id})")

    # 2. Proceed with actual downstream execution
    response = await call_next(request)

    # 3. Post-execution telemetry & Rules Evaluation
    process_time = time.time() - start_time
    trace["process_time_ms"] = round(process_time * 1000, 2)
    trace["response_status"] = response.status_code
    
    if response.status_code >= 400:
        # Trigger Hard Kill Switch sequence if the downstream rejected the action
        trace["status"] = "failed"
        print(f"[KILL SWITCH] Agent action failed ({response.status_code}). Analying for Compensating Transactions...")
        
        # Fire off the async Temporal workflow
        asyncio.create_task(trigger_rollback_workflow(trace_id))
    else:
        trace["status"] = "success"

    return response

@app.get("/api/agent/status")
async def get_agent_status():
    return {"status": "Agent is bounded by Safety Net and running securely."}

@app.post("/api/agent/action")
async def execute_agent_action(action: dict):
    # Mocking downstream agent framework (LangChain/AutoGen) processing an action
    if action.get("type") == "DANGEROUS_ACTION":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Action blocked by Agent Contract limit.")
    
    return {"result": f"Action executed.", "details": action}

@app.get("/api/traces")
async def get_traces():
    # Provide the execution telemetry to the Next.js visual dashboard
    return JSONResponse(content={"traces": execution_traces[::-1]})  # Reverse chronological
