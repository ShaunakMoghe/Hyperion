import enum
import uuid
from sqlalchemy import DateTime, Enum, Text, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models import Base


class RunStatus(enum.Enum):
    SIMULATED = "SIMULATED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    DEPLOYED = "DEPLOYED"
    ROLLED_BACK = "ROLLED_BACK"
    BLOCKED_DRIFT = "BLOCKED_DRIFT"
    FAILED = "FAILED"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    issue_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus), nullable=False, default=RunStatus.SIMULATED
    )
    
    # Simulation fields
    version_marker: Mapped[dict] = mapped_column(JSON, nullable=True)
    tool_plan: Mapped[dict] = mapped_column(JSON, nullable=True)
    changelist: Mapped[dict] = mapped_column(JSON, nullable=True)
    slack_preview: Mapped[dict] = mapped_column(JSON, nullable=True)
    
    # Approval
    approved_by: Mapped[str] = mapped_column(String, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
