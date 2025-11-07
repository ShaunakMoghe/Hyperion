from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness probe")
def healthz() -> dict[str, str]:
    """Return a simple health status payload."""

    settings = get_settings()
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}
