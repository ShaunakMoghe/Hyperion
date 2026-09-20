"""H-052: policy engine unit tests (pure: no DB, no network)."""

import pytest

from hyperion.executor import policy


def _pol(rules, default="allow"):
    return {"default": default, "rules": rules}


def test_default_allow():
    assert policy.decide(_pol([]), "crm", "leads.read", {})[0] == "allow"


def test_default_deny_allowlist_style():
    assert policy.decide(_pol([], "deny"), "crm", "leads.read", {})[0] == "deny"


def test_explicit_deny_rule():
    p = _pol([{"match": {"system": "crm", "operation": "x"},
               "effect": "deny"}])
    assert policy.decide(p, "crm", "x", {})[0] == "deny"
    assert policy.decide(p, "crm", "y", {})[0] == "allow"


def test_require_approval_rule():
    p = _pol([{"match": {"system": "crm", "operation": "emails.send"},
               "effect": "require_approval"}])
    assert policy.decide(p, "crm", "emails.send", {})[0] == "require_approval"


def test_over_threshold_requires_approval():
    p = _pol([{"match": {"system": "crm", "operation": "deals.create",
                         "when": "amount_cents > 100000"},
               "effect": "require_approval"}])
    assert policy.decide(p, "crm", "deals.create",
                         {"amount_cents": 50})[0] == "allow"
    assert policy.decide(p, "crm", "deals.create",
                         {"amount_cents": 500000})[0] == "require_approval"


def test_compound_condition():
    p = _pol([{"match": {"system": "s", "operation": "o",
                         "when": 'stage == "open" and amount_cents >= 10'},
               "effect": "deny"}])
    assert policy.decide(p, "s", "o", {"stage": "open",
                                       "amount_cents": 10})[0] == "deny"
    assert policy.decide(p, "s", "o", {"stage": "closed",
                                       "amount_cents": 10})[0] == "allow"


def test_malformed_args_deny():
    assert policy.decide(_pol([]), "crm", "x", "not-a-dict")[0] == "deny"
    assert policy.decide(_pol([]), "crm", "x", None)[0] == "deny"


@pytest.mark.parametrize("when", [
    "__import__('os').system('x')",  # call
    "a + b",  # binop
    "x.attr",  # attribute
    "amount_cents",  # non-boolean
    "nope > 1",  # unknown arg
    "amount_cents >",  # syntax error
    "[x for x in y]",  # comprehension
])
def test_unsafe_or_bad_conditions_deny(when):
    p = _pol([{"match": {"system": "s", "operation": "o", "when": when},
               "effect": "allow"}])
    effect, reason = policy.decide(p, "s", "o", {"amount_cents": 5})
    assert effect == "deny", reason


def test_missing_policy_file_reports_error(tmp_path):
    loaded, error = policy.load_policy(tmp_path / "nope.yaml")
    assert loaded is None and "missing" in error


def test_unparsable_policy_reports_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("rules: [unclosed")
    loaded, error = policy.load_policy(bad)
    assert loaded is None and "unparsable" in error


def test_bad_rule_shape_reports_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("default: allow\nrules:\n  - {match: {system: s}}")
    loaded, error = policy.load_policy(bad)
    assert loaded is None and "match" in error


def test_good_file_loads(tmp_path):
    good = tmp_path / "policy.yaml"
    good.write_text("default: allow\nrules:\n"
                    "  - match: {system: crm, operation: emails.send}\n"
                    "    effect: require_approval\n")
    loaded, error = policy.load_policy(good)
    assert error is None


def test_validate_policy_accepts_good_dict():
    assert policy.validate_policy(_pol([])) is None
    assert policy.validate_policy(_pol([], "deny")) is None


@pytest.mark.parametrize("bad, fragment", [
    ("nope", "mapping"),
    ({"default": "bogus", "rules": []}, "bad default"),
    ({"default": "allow", "rules": "nope"}, "must be a list"),
    ({"default": "allow", "rules": ["nope"]}, "must be a mapping"),
    ({"default": "allow", "rules": [{"match": {"system": "s"}}]},
     "match.system"),
    ({"default": "allow",
      "rules": [{"match": {"system": "s", "operation": "o"},
                 "effect": "bogus"}]}, "bad effect"),
    ({"default": "allow",
      "rules": [{"match": {"system": "s", "operation": "o", "when": 5},
                 "effect": "allow"}]}, "when must be a string"),
])
def test_validate_policy_rejects_malformed_dicts(bad, fragment):
    assert fragment in policy.validate_policy(bad)


def test_good_file_decides_require_approval(tmp_path):
    good = tmp_path / "policy.yaml"
    good.write_text("default: allow\nrules:\n"
                    "  - match: {system: crm, operation: emails.send}\n"
                    "    effect: require_approval\n")
    loaded, error = policy.load_policy(good)
    assert error is None
    assert policy.decide(loaded, "crm", "emails.send", {})[0] \
        == "require_approval"
