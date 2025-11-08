from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.db.session import SessionLocal

router = APIRouter()


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


@router.get("")
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Health check endpoint.
    """
    db_status = "ok"
    db_error = None
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = "error"
        db_error = str(e)

    if db_status == "ok":
        return {"status": "ok", "database": db_status}
    else:
        return {"status": "error", "database": db_status, "detail": db_error}
