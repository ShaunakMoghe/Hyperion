import logging
import pathlib
import uuid
from fastapi import APIRouter
from app.schemas.simulate import SimulateRequest, SimulateResponse

logging.info("SIMULATE LOADED FROM: %s", pathlib.Path(__file__).resolve())

router = APIRouter()

@router.post("/", summary="Simulate (debug)", response_model=SimulateResponse)
async def simulate_debug(sim_in: SimulateRequest):
    return SimulateResponse(
        run_id=str(uuid.uuid4()),
        changelist=["- Did a thing", "- Did another thing"],
        slack_preview={"channel": "#general", "text": "A thing happened"},
        version_marker={"a": 1, "b": 2},
        tool_plan={"steps": []},
    )