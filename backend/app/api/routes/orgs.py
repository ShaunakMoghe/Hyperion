import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.organization import Organization
from app.schemas.org import OrganizationCreate, OrganizationRead
from app.services.audit import log_event
from app.utils.slugify import slugify

router = APIRouter(prefix="/orgs", tags=["orgs"])


@router.post("/", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
def create_org(payload: OrganizationCreate, db: Session = Depends(get_db)) -> OrganizationRead:
    """Create a new organization."""

    slug = payload.slug or slugify(payload.name)

    org = Organization(name=payload.name, slug=slug)
    db.add(org)
    try:
        db.commit()
    except IntegrityError as exc:  # pragma: no cover - FastAPI handles response
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization name or slug already exists.",
        ) from exc

    db.refresh(org)
    log_event(db, action="org.created", organization_id=org.id, target=f"org:{org.id}", context={"name": org.name})
    return OrganizationRead.model_validate(org)


@router.get("/", response_model=list[OrganizationRead])
def list_orgs(db: Session = Depends(get_db)) -> list[OrganizationRead]:
    """List organizations in ascending creation order."""

    orgs = db.query(Organization).order_by(Organization.created_at.asc()).all()
    return [OrganizationRead.model_validate(org) for org in orgs]
