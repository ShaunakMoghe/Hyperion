import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AuditLogRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    action: str = Field(max_length=255)
    target: str | None = Field(default=None, max_length=255)
    context: dict | None = None
    message: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
