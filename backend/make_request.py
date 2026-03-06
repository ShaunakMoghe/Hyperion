import requests

requests.post('http://localhost:8000/api/agent/action', json={"type": "READ_CRM", "query": "customer_data"})
requests.post('http://localhost:8000/api/agent/action', json={"type": "DANGEROUS_ACTION", "query": "delete_inbox"})
print("Sent test requests.")
