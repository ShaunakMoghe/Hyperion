import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from app.models.run import RunStatus


class RunCreate(BaseModel):
    issue_url: str


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    issue_url: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
