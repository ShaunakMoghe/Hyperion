import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_event(
    db: Session,
    *,
    action: str,
    organization_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    target: str | None = None,
    context: dict[str, Any] | None = None,
    message: str | None = None,
) -> AuditLog:
    """Persist an audit log entry and return it."""

    entry = AuditLog(
        action=action,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        target=target,
        context=context,
        message=message,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
