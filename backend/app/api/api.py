import logging
import pathlib
from fastapi import APIRouter
from app.api.routes import runs, health, simulate

logging.info("API LOADED FROM: %s", pathlib.Path(__file__).resolve())

api_router = APIRouter()
api_router.include_router(runs.router,    prefix="/runs",    tags=["runs"])
api_router.include_router(health.router,  prefix="/health",  tags=["health"])
api_router.include_router(simulate.router, prefix="/simulate", tags=["simulate"])