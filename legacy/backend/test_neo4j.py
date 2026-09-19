import asyncio
from neo4j import AsyncGraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "agentrollback123"

async def test_neo4j():
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        await driver.verify_connectivity()
        print("Successfully connected to Neo4j")
        
        query = """
        MATCH (a:AgentIntent)-[r1:EXECUTED]->(c:APICall)-[r2:CAPTURED_STATE]->(s:StateSnapshot)
        RETURN a, r1, c, r2, s
        LIMIT 5
        """
        async with driver.session() as session:
            result = await session.run(query)
            records = await result.data()
            print(f"Found {len(records)} stored causal chains in Graph DB.")
            for r in records:
                print(r)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await driver.close()

if __name__ == "__main__":
    asyncio.run(test_neo4j())
