"""LLM provider interface + Gemini implementation (H-061 groundwork).

- No model names are hardcoded: provider and model come from
  HYPERION_LLM_PROVIDER / HYPERION_LLM_MODEL.
- Temperature 0; JSON mode for spec proposals.
- Cost: the configured Gemini key is free-tier, so reported cost is 0.0
  and the USD cap alone can never trip. The token cap
  (HYPERION_LLM_TOKEN_BUDGET, default 1000000) is the binding constraint:
  tokens are fully accounted and BudgetTracker aborts when either cap is
  exceeded, before and after each call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Completion:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


class Provider(Protocol):
    def complete(self, prompt: str) -> Completion:
        """Complete with temperature 0, JSON mode. Raises on API failure."""
        ...  # pragma: no cover


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class BudgetTracker:
    cap_usd: float = field(default_factory=lambda: float(
        os.environ.get("HYPERION_LLM_BUDGET_USD", "20")))
    spent_usd: float = 0.0
    calls: int = 0
    tokens: int = 0
    cap_tokens: int = field(default_factory=lambda: int(
        os.environ.get("HYPERION_LLM_TOKEN_BUDGET", "1000000")))

    def check(self) -> None:
        """Raise BudgetExceeded when a cap is already exhausted (pre-call)."""
        if self.spent_usd > self.cap_usd:
            raise BudgetExceeded(
                f"LLM spend ${self.spent_usd:.4f} exceeded cap ${self.cap_usd}")
        if self.tokens > self.cap_tokens:
            raise BudgetExceeded(
                f"LLM tokens {self.tokens} exceeded cap {self.cap_tokens}")

    def add(self, completion: Completion) -> None:
        self.spent_usd += completion.cost_usd
        self.calls += 1
        self.tokens += completion.prompt_tokens + completion.completion_tokens
        self.check()


class GeminiProvider:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError("Gemini API key missing")
        if not model:
            raise ValueError("HYPERION_LLM_MODEL is empty")
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    def complete(self, prompt: str) -> Completion:
        response = self._client.models.generate_content(
            model=self._model, contents=prompt,
            config={"temperature": 0.0,
                    "response_mime_type": "application/json"},
        )
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
        completion_tokens = getattr(usage, "candidates_token_count", 0) or 0
        return Completion(text=response.text or "", model=self._model,
                          prompt_tokens=prompt_tokens,
                          completion_tokens=completion_tokens, cost_usd=0.0)


def from_env() -> tuple[str, str, str]:
    """Return (provider, model, api_key_env_name); fail closed on gaps."""
    provider = os.environ.get("HYPERION_LLM_PROVIDER", "")
    model = os.environ.get("HYPERION_LLM_MODEL", "")
    if provider != "gemini":
        raise ValueError(
            f"unsupported HYPERION_LLM_PROVIDER {provider!r} (only 'gemini')")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY missing")
    return provider, model, api_key


def make_provider() -> Provider:
    provider, model, api_key = from_env()
    if provider == "gemini":
        return GeminiProvider(api_key, model)
    raise ValueError(f"unsupported provider {provider!r}")  # unreachable
