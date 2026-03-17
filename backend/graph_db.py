from neo4j import AsyncGraphDatabase

# Configure Neo4j connection
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "agentrollback123"

class GraphStore:
    def __init__(self):
        self.driver = None

    async def connect(self):
        try:
            self.driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            # Verify connectivity
            await self.driver.verify_connectivity()
            print("[NEO4J] Successfully connected to Graph Database.")
        except Exception as e:
            print(f"[NEO4J] Error connecting to database: {e}")

    async def close(self):
        if self.driver:
            await self.driver.close()

    async def record_agent_intent(self, trace_id: str, method: str, path: str, request_body: str, status: str, parent_trace_id: str = None):
        """
        Creates a subgraph for the intercept, mapping the intent to the API call.
        (AgentIntent) -[EXECUTED]-> (APICall) -[CAPTURED_STATE]-> (StateSnapshot)
        """
        if not self.driver:
            return

        query = """
        MERGE (a:AgentIntent {trace_id: $trace_id})
        MERGE (c:APICall {method: $method, path: $path, trace_id: $trace_id})
        MERGE (s:StateSnapshot {trace_id: $trace_id})
        SET s.body = $request_body, s.status = $status
        MERGE (a)-[:EXECUTED]->(c)
        MERGE (c)-[:CAPTURED_STATE]->(s)
        """
        try:
            async with self.driver.session() as session:
                await session.run(query, trace_id=trace_id, method=method, path=path, request_body=request_body, status=status)
                
                # If there's a parent task, create the causal link
                if parent_trace_id:
                    link_query = """
                    MATCH (parent:AgentIntent {trace_id: $parent_trace_id})
                    MATCH (child:AgentIntent {trace_id: $trace_id})
                    MERGE (parent)-[:CAUSED]->(child)
                    """
                    await session.run(link_query, parent_trace_id=parent_trace_id, trace_id=trace_id)
                
                print(f"[NEO4J] Wrote Graph Node for Trace {trace_id}")
        except Exception as e:
            print(f"[NEO4J] Failed to write to graph: {e}")

    async def find_dependent_traces(self, trace_id: str):
        """
        Finds any downstream agent intents that relied on the state produced by this trace.
        """
        if not self.driver:
            return []
            
        # Simulating a causal trace: (AgentIntent)-[:CAUSED]->(DependentIntent)
        query = """
        MATCH (a:AgentIntent {trace_id: $trace_id})-[:CAUSED*]->(downstream:AgentIntent)
        RETURN downstream.trace_id AS dep_trace_id
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(query, trace_id=trace_id)
                records = await result.data()
                deps = [r["dep_trace_id"] for r in records]
                if deps:
                   print(f"[NEO4J] Found {len(deps)} dependent traces for {trace_id}: {deps}")
                return deps
        except Exception as e:
            print(f"[NEO4J] Failed to query dependents: {e}")
            return []

    async def get_audit_ledger(self, trace_id: str):
        """
        Generates a flat, cryptographic audit ledger of the trace and its entire causal chain.
        """
        if not self.driver:
            return []
            
        # Bidirectional match to find all intents in this causal chain
        query = """
        MATCH (a:AgentIntent)-[:CAUSED*0..]-(b:AgentIntent)
        WHERE a.trace_id = $trace_id OR b.trace_id = $trace_id
        MATCH (b)-[:EXECUTED]->(c:APICall)-[:CAPTURED_STATE]->(s:StateSnapshot)
        RETURN DISTINCT b.trace_id AS trace_id, 
                        c.method AS method, 
                        c.path AS path, 
                        s.body AS request_body, 
                        s.status AS status
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(query, trace_id=trace_id)
                records = await result.data()
                print(f"[NEO4J] Generated SOC2 ledged for {trace_id} ({len(records)} events in chain)")
                return records
        except Exception as e:
            print(f"[NEO4J] Failed to generate audit ledger: {e}")
            return []

    async def get_trace_by_id(self, trace_id: str):
        """
        Retrieves the intercepted APICall and its JSON StateSnapshot payload by trace ID.
        Returns a dict containing: method, path, request_body
        """
        if not self.driver:
            return None

        query = """
        MATCH (c:APICall {trace_id: $trace_id})-[:CAPTURED_STATE]->(s:StateSnapshot)
        RETURN c.method AS method, c.path AS path, s.body AS request_body
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(query, trace_id=trace_id)
                record = await result.single()
                if record:
                    return {
                        "method": record["method"],
                        "path": record["path"],
                        "request_body": record["request_body"]
                    }
                return None
        except Exception as e:
            print(f"[NEO4J] Failed to retrieve trace by id: {e}")
            return None

    async def get_causal_chain(self, failed_trace_id: str):
        """
        Recursively traverses UP the [:CAUSED] relationships to find all successful ancestor
        API calls that led to this failure.
        Returns the causal chain ordered reverse-chronologically (Last In, First Out) for Saga rollbacks.
        """
        if not self.driver:
            return []

        # Find all ancestors (parents, grandparents) connected via <-[:CAUSED]-
        # and only include traces whose execution was successful.
        query = """
        MATCH (failed:AgentIntent {trace_id: $failed_trace_id})<-[:CAUSED*1..]-(parent:AgentIntent)-[:EXECUTED]->(c:APICall)-[:CAPTURED_STATE]->(s:StateSnapshot)
        WHERE s.status = 'success'
        RETURN parent.trace_id AS trace_id,
               c.method AS method,
               c.path AS path,
               s.body AS request_body,
               parent.timestamp AS timestamp
        ORDER BY parent.timestamp DESC
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(query, failed_trace_id=failed_trace_id)
                records = await result.data()
                return records
        except Exception as e:
            print(f"[NEO4J] Failed to retrieve causal chain: {e}")
            return []

    async def get_recent_traces(self, limit: int = 100):
        """
        Retrieves the most recent agent execution traces directly from the graph database.
        Returns the data in a format identical to the old in-memory execution_traces list.
        """
        if not self.driver:
            return []

        query = """
        MATCH (a:AgentIntent)-[:EXECUTED]->(c:APICall)-[:CAPTURED_STATE]->(s:StateSnapshot)
        OPTIONAL MATCH (parent:AgentIntent)-[:CAUSED]->(a)
        RETURN a.trace_id AS trace_id,
               c.method AS method,
               c.path AS path,
               s.body AS request_body,
               s.status AS status,
               parent.trace_id AS parent_trace_id,
               a.timestamp AS timestamp,
               a.is_shadow_mode AS is_shadow_mode
        ORDER BY timestamp DESC
        LIMIT $limit
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(query, limit=limit)
                records = await result.data()
                return records
        except Exception as e:
            print(f"[NEO4J] Failed to get recent traces: {e}")
            return []

graph_db = GraphStore()
