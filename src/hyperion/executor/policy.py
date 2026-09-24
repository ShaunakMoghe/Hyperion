"""Policy engine (H-052): YAML allow/deny/require_approval rules.

Migrates the v1 contract concepts (forbidden actions -> deny rules;
spending/attribute guards -> `when` conditions) into a fail-closed engine:

- Missing policy file, unparsable YAML, bad rule shape, unparsable `when`,
  or malformed (non-dict) args all decide DENY, with a reason.
- `when` uses a safe expression subset evaluated over a hand-walked AST —
  never `eval`: comparisons, and/or/not, literals, and bare arg names only.

Policy file shape:
    default: allow          # or deny (allowlist style, like the v1 contract)
    rules:
      - match: {system: crm, operation: emails.send}
        effect: require_approval
      - match: {system: crm, operation: deals.create,
                when: "amount_cents > 100000"}
        effect: require_approval
"""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

ALLOW = "allow"
DENY = "deny"
REQUIRE_APPROVAL = "require_approval"

# Note: Load/Store/Del are expression *contexts* attached to every Name;
# Load must be allowed or no condition can reference an arg.
_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.UnaryOp, ast.Compare, ast.Name,
    ast.Constant, ast.And, ast.Or, ast.Not,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Load,
)


def _check_nodes(tree: ast.AST) -> bool:
    return all(isinstance(node, _ALLOWED_NODES) for node in ast.walk(tree))


def _eval(node: ast.AST, args: dict):
    if isinstance(node, ast.Expression):
        return _eval(node.body, args)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in args:
            raise KeyError(f"unknown arg {node.id!r}")
        return args[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval(node.operand, args)
    if isinstance(node, ast.BoolOp):
        values = [_eval(v, args) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left, right = _eval(node.left, args), _eval(node.comparators[0], args)
        op = node.ops[0]
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        try:
            if isinstance(op, ast.Lt):
                return left < right
            if isinstance(op, ast.LtE):
                return left <= right
            if isinstance(op, ast.Gt):
                return left > right
            if isinstance(op, ast.GtE):
                return left >= right
        except TypeError as e:
            raise ValueError(f"uncomparable operands: {e}") from e
    raise ValueError(f"unsupported expression {ast.dump(node)}")


def condition_holds(when: str, args: dict) -> bool:
    """Evaluate a `when` condition; True/False, never raises outwardly here.

    Raises ValueError/KeyError/SyntaxError on bad input; callers fail closed.
    """
    tree = ast.parse(when, mode="eval")
    if not _check_nodes(tree):
        raise ValueError(f"disallowed syntax in {when!r}")
    result = _eval(tree, args)
    if not isinstance(result, bool):
        raise ValueError(f"condition must be boolean, got {result!r}")
    return result


def validate_policy(policy) -> str | None:
    """Check a caller-supplied policy dict. None when valid, else reason.

    Dicts passed via `execute(policy=...)` skip `load_policy`, so the
    executor runs this first; an invalid dict decides DENY, never raises.
    """
    if not isinstance(policy, dict):
        return "policy must be a mapping"
    default = policy.get("default", ALLOW)
    if default not in (ALLOW, DENY):
        return f"bad default {default!r}"
    rules = policy.get("rules", [])
    if not isinstance(rules, list):
        return "policy rules must be a list"
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            return f"rule {i} must be a mapping"
        match = rule.get("match")
        if not isinstance(match, dict) or "system" not in match \
                or "operation" not in match:
            return f"rule {i} needs match.system/match.operation"
        if rule.get("effect") not in (ALLOW, DENY, REQUIRE_APPROVAL):
            return f"rule {i} has bad effect"
        if "when" in match and not isinstance(match["when"], str):
            return f"rule {i} when must be a string"
    return None


def _finish(raw) -> tuple[dict | None, str | None]:
    if not isinstance(raw, dict):
        return None, "policy root must be a mapping"
    error = validate_policy(raw)
    if error is not None:
        return None, error
    return {"default": raw.get("default", ALLOW),
            "rules": raw.get("rules", [])}, None


def loads_policy(text: str) -> tuple[dict | None, str | None]:
    """Parse policy YAML text. Returns (policy, error); error fails closed.

    Lets callers hash and parse the exact bytes they read (no TOCTOU
    between a validation read and a later enforcement read).
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return None, f"unparsable: {e}"
    return _finish(raw)


def load_policy(path: str | Path) -> tuple[dict | None, str | None]:
    """Load a policy file. Returns (policy, error); error set fails closed."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, f"policy file {path} missing"
    except (OSError, UnicodeDecodeError) as e:
        return None, f"policy file {path} unreadable: {e}"
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return None, f"policy file {path} unparsable: {e}"
    return _finish(raw)


def decide(policy: dict, system: str, operation: str, args: dict) -> tuple[str, str]:
    """Decide allow/deny/require_approval. Malformed args decide deny."""
    if not isinstance(args, dict):
        return DENY, "malformed args (not a mapping)"
    for rule in policy["rules"]:
        match = rule["match"]
        if match["system"] != system or match["operation"] != operation:
            continue
        when = match.get("when")
        if when is not None:
            try:
                if not condition_holds(when, args):
                    continue
            except (ValueError, KeyError, SyntaxError, TypeError,
                    RecursionError) as e:
                return DENY, f"bad condition: {e}"
        return rule["effect"], f"rule {match}"
    return policy["default"], "default"
