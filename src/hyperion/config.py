"""Runtime configuration from environment variables.

Uses pathlib for filesystem paths; no POSIX-only assumptions.
No model names are hardcoded: the provider and model come from
HYPERION_LLM_PROVIDER / HYPERION_LLM_MODEL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _budget() -> float:
    raw = os.environ.get("HYPERION_LLM_BUDGET_USD", "20")
    try:
        return float(raw)
    except ValueError:
        return 20.0


def _env(name: str) -> str:
    return os.environ.get(name, "")


@dataclass
class Config:
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", "postgresql://hyperion:changeme@localhost:5432/hyperion"
        )
    )
    llm_budget_usd: float = field(default_factory=_budget)
    llm_provider: str = field(default_factory=lambda: _env("HYPERION_LLM_PROVIDER"))
    llm_model: str = field(default_factory=lambda: _env("HYPERION_LLM_MODEL"))
    repo_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])


def load() -> Config:
    return Config()
