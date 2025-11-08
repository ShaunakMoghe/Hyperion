import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import SessionLocal
from app.models.run import Run, RunStatus
from app.schemas.run import RunCreate, RunOut

router = APIRouter()


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


@router.post("", response_model=RunOut, status_code=201)
async def create_run(
    run_in: RunCreate, db: AsyncSession = Depends(get_db)
) -> Run:
    """
    Create a new run.
    """
    run = Run(issue_url=run_in.issue_url, status=RunStatus.SIMULATED)
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


@router.get("/{run_id}", response_model=RunOut)
async def get_run(
    run_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> Run:
    """
    Get a single run by ID.
    """
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
