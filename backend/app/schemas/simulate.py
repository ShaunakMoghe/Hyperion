from pydantic import BaseModel

class SimulateRequest(BaseModel):
    issue_url: str
    draft_with_ai: bool | None = False

class SimulateResponse(BaseModel):
    run_id: str
    changelist: list[str]
    slack_preview: dict
    version_marker: dict
    tool_plan: dict
