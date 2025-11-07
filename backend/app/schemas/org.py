import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OrganizationBase(BaseModel):
    name: str = Field(max_length=255)
    slug: str | None = Field(default=None, max_length=255)


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationRead(OrganizationBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
