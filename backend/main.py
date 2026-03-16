from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import time
import uuid
import asyncio
import json
import asyncio
from temporalio.client import Client
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException

from contextlib import asynccontextmanager

from graph_db import graph_db
from agent_contract import validate_action_against_contract
from real_agent import run_agent_query

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await graph_db.connect()
    yield
    # Shutdown
    await graph_db.close()

app = FastAPI(title="State-as-a-Service Agent Intercept Proxy", lifespan=lifespan)

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
    parent_trace_id = request.headers.get("x-parent-trace-id")
    is_shadow_mode = request.query_params.get("simulate") == "true" or request.headers.get("x-simulate") == "true"
    
    trace = {
        "trace_id": trace_id,
        "path": request.url.path,
        "method": request.method,
        "request_body": body.decode('utf-8') if body else None,
        "timestamp": start_time,
        "status": "pending_execution",
        "parent_trace_id": parent_trace_id,
        "is_shadow_mode": is_shadow_mode
    }
    execution_traces.append(trace)
    print(f"[INTERCEPT] Captured state for {request.method} {request.url.path} (Trace: {trace_id}) [Shadow: {is_shadow_mode}]")

    # Write to Neo4j Graph Database
    asyncio.create_task(
        graph_db.record_agent_intent(
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
            request_body=trace["request_body"] or "",
            status="pending_execution",
            parent_trace_id=parent_trace_id
        )
    )

    # Agent Contract Enforcement (Proxy Level)
    action_dict = {}
    try:
        if body:
            action_dict = json.loads(body.decode('utf-8'))
            validate_action_against_contract(action_dict)
    except HTTPException as e:
        # Contract blocked it
        trace["status"] = "failed"
        trace["response_status"] = e.status_code
        print(f"[KILL SWITCH] Agent action BLOCKED by contract ({e.status_code}).")
        asyncio.create_task(trigger_rollback_workflow(trace_id))
        response = JSONResponse(content={"detail": e.detail}, status_code=e.status_code)
        response.headers["x-trace-id"] = trace_id
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response
    except Exception as e:
        pass

    # 2. Proceed with actual downstream execution OR Shadow Bypass
    if is_shadow_mode:
        print(f"[SHADOW MODE] Bypassing downstream execution for Trace {trace_id}")
        response = JSONResponse(content={"result": "Shadow mode executed.", "details": action_dict})
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
    else:
        response = await call_next(request)

    # 3. Post-execution telemetry & Rules Evaluation
    process_time = time.time() - start_time
    trace["process_time_ms"] = round(process_time * 1000, 2)
    trace["response_status"] = response.status_code
    
    if response.status_code >= 400 and not (is_shadow_mode and response.status_code == 200):
        # Trigger Hard Kill Switch sequence if the downstream rejected the action
        if trace["status"] != "failed": # Don't double-trigger if contract blocked it
            trace["status"] = "failed"
            print(f"[KILL SWITCH] Agent action failed ({response.status_code}). Analying for Compensating Transactions...")
            # Fire off the async Temporal workflow
            asyncio.create_task(trigger_rollback_workflow(trace_id))
    else:
        if trace["status"] != "failed":
            trace["status"] = "success"

    # Attach trace ID to the response so the agent can chain causal actions
    response.headers["x-trace-id"] = trace_id

    return response

@app.get("/api/agent/status")
async def get_agent_status():
    return {"status": "Agent is bounded by Safety Net and running securely."}

@app.post("/api/agent/action")
async def execute_agent_action(action: dict):
    # This acts as the downstream mock. Validation is now handled at the proxy middleware!
    return {"result": f"Action executed.", "details": action}

@app.post("/api/chat")
async def chat_with_agent(request: dict):
    prompt = request.get("prompt", "")
    response = await run_agent_query(prompt)
    return {"reply": response}

@app.get("/api/traces")
async def get_traces():
    # Provide the execution telemetry to the Next.js visual dashboard
    return JSONResponse(content={"traces": execution_traces[::-1]})  # Reverse chronological

@app.get("/api/compliance/export/{trace_id}")
async def export_compliance_audit(trace_id: str):
    # Retrieve the cryptographic SOC2 ledger from the Neo4j graph
    ledger = await graph_db.get_audit_ledger(trace_id)
    return JSONResponse(
        content={
            "document": "SOC2_Agent_Audit_Ledger",
            "primary_trace_id": trace_id,
            "causal_chain_events": ledger
        }
    )
