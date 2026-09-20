"""Inverse-spec proposer (H-061): LLM proposes, everything is logged.

Per operation the prompt carries: its OpenAPI fragment, sibling operations
on the same resource, candidate reads, candidate inverse ops, and few-shot
examples from human specs EXCLUDING the hold-out set (H-065). Output must
validate against the spec schema. Temperature 0; model id, prompt hash,
tokens, and cost are logged; proposals cache by
(operation, spec version, prompt version, model, prompt content hash).
Budget pre-checked before and accounted after each call.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from hyperion.specs import loader

from .llm import BudgetTracker, Provider

PROMPT_VERSION = "v2"

# Ground truth NEVER shown as few-shot examples (H-065).
HOLDOUT_IDS = {
    "stripe.products.create",
    "stripe.coupons.create",
    "crm.notes.add",
}


def load_examples(specs_dirs: list[Path]) -> list[dict]:
    """Human specs usable as few-shot examples (hold-out excluded)."""
    examples = []
    for specs_dir in specs_dirs:
        if not specs_dir.is_dir():
            continue
        for spec in loader.load_dir(specs_dir).values():
            if spec["id"] not in HOLDOUT_IDS:
                examples.append(spec)
    return sorted(examples, key=lambda s: s["id"])


def operation_context(operation: dict, siblings: list[dict],
                      reads: list[dict], inverses: list[dict]) -> dict:
    return {"operation": operation, "siblings": siblings,
            "candidate_reads": reads, "candidate_inverses": inverses}


def build_prompt(spec_version: str, context: dict,
                 examples: list[dict], operation_id: str | None = None) -> str:
    """Deterministic prompt; returns text (hash it for the log).

    Hold-out ids are re-filtered here (defense in depth): load_examples
    filters, but any caller-supplied list passes through this gate too, so
    ground truth can never leak into few-shot examples.
    """
    examples = [e for e in examples
                if e.get("id") not in HOLDOUT_IDS]
    lines = [
        f"You write Hyperion inverse specs (spec_version {spec_version}, "
        f"prompt {PROMPT_VERSION}).",
        "Reply with exactly one YAML object matching this shape:",
        "spec_version|id|system|operation{method,path}|effect_class|fidelity|"
        "before_image{read{method,path,params},fields}|produces[{name,from}]|"
        "inverse{operation,params,body_from_before_image}|"
        "verify{read,compare{fields,against}}|provenance.",
        "spec_version is the integer 1.",
    ]
    if operation_id is not None:
        lines.append(f"id must be exactly {operation_id}.")
    else:
        lines.append("id is <system>.<resource>.<verb>.")
    lines += [
        "compare.against is before_image (updates/deletes) or response "
        "(creates), never null.",
        "compare may add expect ONLY for terminal values the API itself "
        "reports (example: a canceled intent reports status canceled). "
        "For deletes, omit expect: absence (404/410) verifies the removal; "
        "never guess tombstone shapes like deleted:true.",
        "Template roots allowed: $.args $.response $.produced $.before_image.",
        "effect_class/fidelity pairs allowed: read/exact, "
        "reversible/exact|equivalent, compensable/compensated, "
        "irreversible/none. reads and irreversibles have inverse:null.",
        "Creates (server-generated ids) have before_image:null, produce the "
        "id from $.response.<id>, and consume it as $.produced.<id>.",
        "OPERATION:",
        json.dumps(context["operation"], sort_keys=True),
        "SIBLINGS:",
        json.dumps(context["siblings"], sort_keys=True),
        "CANDIDATE_READS:",
        json.dumps(context["candidate_reads"], sort_keys=True),
        "CANDIDATE_INVERSES:",
        json.dumps(context["candidate_inverses"], sort_keys=True),
        "EXAMPLES:",
    ]
    for example in examples:
        lines.append(yaml.safe_dump(example, sort_keys=True))
    lines.append("Reply with the YAML object only, no prose.")
    return "\n".join(lines)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def cache_path(cache_dir: Path, operation_id: str, spec_commit: str,
               model: str, prompt_hash_hex: str) -> Path:
    """Cache file keyed by operation, spec pin, prompt version, model, AND
    prompt content hash: prompt/context/example changes must never hit a
    stale entry written for different prompt text."""
    safe_model = "".join(c if c.isalnum() or c in "-." else "_"
                         for c in model)
    return cache_dir / (f"{operation_id}__{spec_commit[:12]}__"
                        f"{PROMPT_VERSION}__{safe_model}__"
                        f"{prompt_hash_hex[:16]}.json")


def propose(provider: Provider, model: str, spec_version: str,
            operation_id: str, context: dict, examples: list[dict],
            cache_dir: Path, spec_commit: str,
            budget: BudgetTracker) -> tuple[dict, dict]:
    """Return (spec, evidence). Cached; budget enforced before each call."""
    prompt = build_prompt(spec_version, context, examples,
                          operation_id=operation_id)
    phash = prompt_hash(prompt)
    budget.check()  # refuse the API call when already exhausted
    path = cache_path(cache_dir, operation_id, spec_commit, model, phash)
    if path.is_file():
        cached = json.loads(path.read_text(encoding="utf-8"))
        return cached["spec"], {**cached["evidence"], "cached": True}
    completion = provider.complete(prompt)
    budget.add(completion)
    try:
        spec = yaml.safe_load(completion.text)
    except yaml.YAMLError as e:
        raise ValueError(f"proposer returned invalid YAML: {e}") from e
    if not isinstance(spec, dict):
        raise ValueError("proposer returned non-mapping YAML")
    evidence = {"model": completion.model, "prompt_hash": phash,
                "prompt_version": PROMPT_VERSION,
                "prompt_tokens": completion.prompt_tokens,
                "completion_tokens": completion.completion_tokens,
                "cost_usd": completion.cost_usd,
                "spec_commit": spec_commit, "cached": False}
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"spec": spec, "evidence": evidence},
                               indent=2, sort_keys=True),
                    encoding="utf-8")
    return spec, evidence
