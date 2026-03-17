import os
import json
import requests
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage

# Load environment variables (e.g., OPENAI_API_KEY)
load_dotenv()

PROXY_URL = "http://localhost:8000/api/agent/action"

class AgentSessionWrapper:
    def __init__(self):
        self.session = requests.Session()
        self.last_trace_id = None

    def post(self, url, json_payload):
        headers = {}
        if self.last_trace_id:
            headers["x-parent-trace-id"] = self.last_trace_id
            
        response = self.session.post(url, json=json_payload, headers=headers)
        
        # Capture the new trace ID returned by the proxy to link the next causal step
        new_trace_id = response.headers.get("x-trace-id")
        if new_trace_id:
            self.last_trace_id = new_trace_id
            
        return response

agent_session = AgentSessionWrapper()

@tool
def read_crm_data(query: str) -> str:
    """Reads customer data from the CRM system."""
    print(f"\n[LangChain Tool] Executing read_crm_data with query: {query}")
    try:
        response = agent_session.post(PROXY_URL, json_payload={"type": "READ_CRM", "query": query})
        response.raise_for_status()
        return json.dumps(response.json())
    except requests.exceptions.RequestException as e:
        print(f"❌ Proxy request failed: {e}")
        return f"Error: {e}"

@tool
def delete_inbox(user_id: str) -> str:
    """Deletes an entire email inbox for a given user. DANGEROUS ACTION."""
    print(f"\n[LangChain Tool] Executing delete_inbox for user: {user_id}")
    try:
        response = agent_session.post(PROXY_URL, json_payload={"type": "DANGEROUS_ACTION", "query": f"delete_inbox_{user_id}"})
        response.raise_for_status()
        return json.dumps(response.json())
    except requests.exceptions.RequestException as e:
        status_code = getattr(e.response, 'status_code', 'Unknown')
        print(f"❌ Proxy actively blocked the request! Status Code: {status_code}")
        return f"Error: Action blocked by security policy ({status_code}). Do not attempt bypassing."

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

def get_agent_executor():
    # Check for API key
    if not os.getenv("GEMINI_API_KEY"):
        raise ValueError("GEMINI_API_KEY environment variable is not set.")

    # Initialize the LLM
    llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite-preview", temperature=0)
    
    # Define our tools
    tools = [read_crm_data, delete_inbox]
    
    # Create the agent using langgraph
    agent_executor = create_react_agent(llm, tools=tools)
    return agent_executor

async def run_agent_query(user_prompt: str) -> str:
    try:
        executor = get_agent_executor()
        result = await executor.ainvoke({"messages": [HumanMessage(content=user_prompt)]})
        return result["messages"][-1].content
    except Exception as e:
        return f"Error executing agent: {str(e)}"

if __name__ == "__main__":
    import asyncio
    objective = (
        "You have access to tools to read CRM data and delete inboxes.\n"
        "1. First, use read_crm_data for 'vip_customer_123'. \n"
        "2. Then, based on that data, use delete_inbox for 'vip_customer_123'."
    )
    res = asyncio.run(run_agent_query(objective))
    print("✅ Final Agent Result:", res)
