import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.schemas.audit import AuditLogRead

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/", response_model=list[AuditLogRead])
def list_audit_logs(
    db: Session = Depends(get_db),
    organization_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditLogRead]:
    """Return audit log entries, optionally filtered by organization."""

    query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if organization_id:
        query = query.filter(AuditLog.organization_id == organization_id)

    entries = query.limit(limit).all()
    return [AuditLogRead.model_validate(entry) for entry in entries]
