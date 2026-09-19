import asyncio
import sys
import os

# Add backend directory to path if running from root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from graph_db import graph_db
from rollback_engine import execute_compensating_transaction

async def test_distributed_saga():
    print("--- Testing DISTRIBUTED SAGA (Cross-Platform Rollback) ---")
    
    # 1. Mock Neo4j Responses (since real Neo4j isn't running in this Sandbox)
    async def mock_get_trace_by_id(trace_id):
        if trace_id == "trace-B-failed":
            return {"method": "POST", "path": "/v1/customers", "request_body": '{"email": "lead@example.com"}'}
        return None
        
    async def mock_get_causal_chain(trace_id):
        if trace_id == "trace-B-failed":
            return [
                {
                    "trace_id": "trace-A-success",
                    "method": "POST",
                    "path": "/api/crm/leads",
                    "request_body": '{"name": "Lead A", "id": "lead_123"}',
                    "timestamp": 1234567890
                }
            ]
        return []

    # Inject Mocks
    graph_db.get_trace_by_id = mock_get_trace_by_id
    graph_db.get_causal_chain = mock_get_causal_chain
    
    print("[MOCK DATA] Intercepted failed trace: trace-B-failed (POST /v1/customers)")
    print("[MOCK DATA] Intercepted successful ancestor: trace-A-success (POST /api/crm/leads)\n")
    print("--- Triggering Temporal Rollback Worker for Failed Trace B ---\n")
    
    # 3. Trigger the orchestrated saga rollback
    await execute_compensating_transaction("trace-B-failed")
    
if __name__ == "__main__":
    asyncio.run(test_distributed_saga())
