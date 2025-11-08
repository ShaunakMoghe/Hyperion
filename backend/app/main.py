import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.api import api_router
import pathlib

logging.basicConfig(level=logging.INFO)
logging.info("MAIN LOADED FROM: %s", pathlib.Path(__file__).resolve())

app = FastAPI(title="Hyperion")

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
