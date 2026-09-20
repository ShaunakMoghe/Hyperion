"""H-061/H-062/H-065: proposer, static validator, hold-out (no network)."""

import copy
import json

import pytest
import yaml

from hyperion.specs import loader as spec_loader
from hyperion.synth import proposer, validator, verifier
from hyperion.synth.llm import BudgetExceeded, BudgetTracker, Completion

GOOD_STRIPE = {
    "spec_version": 1, "id": "stripe.products.create", "system": "stripe",
    "operation": {"method": "POST", "path": "/v1/products"},
    "effect_class": "reversible", "fidelity": "equivalent",
    "before_image": None,
    "produces": [{"name": "product_id", "from": "$.response.id"}],
    "inverse": {
        "operation": {"method": "DELETE", "path": "/v1/products/{id}"},
        "params": {"id": "$.produced.product_id"},
        "body_from_before_image": []},
    "verify": {
        "read": {"method": "GET", "path": "/v1/products/{id}",
                 "params": {"id": "$.produced.product_id"}},
        "compare": {"fields": [], "against": "before_image"}},
    "provenance": {"source": "llm_proposed", "model": "m",
                   "verified": False, "trials": 0, "reviewed_by": None},
}

KNOWN = {("POST", "/v1/products"), ("DELETE", "/v1/products/{id}"),
         ("GET", "/v1/products/{id}")}


class FakeProvider:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def complete(self, prompt: str) -> Completion:
        self.calls += 1
        text = yaml.safe_dump(self.payload)
        return Completion(text=text, model="fake",
                          prompt_tokens=len(prompt) // 4,
                          completion_tokens=50)


def _context():
    return proposer.operation_context(
        {"method": "POST", "path": "/v1/products"},
        [{"method": "GET", "path": "/v1/products"}],
        [{"method": "GET", "path": "/v1/products/{id}"}],
        [{"method": "DELETE", "path": "/v1/products/{id}"}])


def test_propose_caches_and_logs(tmp_path):
    provider = FakeProvider(GOOD_STRIPE)
    budget = BudgetTracker(cap_usd=20)
    spec, evidence = proposer.propose(
        provider, "fake", "7ec2459", "stripe.products.create", _context(),
        [], tmp_path, "7ec24599c27c862a0a27fd2c890b564edbd5f8d7", budget)
    assert spec["id"] == "stripe.products.create"
    assert evidence["cached"] is False
    assert evidence["prompt_tokens"] > 0 and evidence["model"] == "fake"
    assert budget.calls == 1
    spec2, evidence2 = proposer.propose(
        provider, "fake", "7ec2459", "stripe.products.create", _context(),
        [], tmp_path, "7ec24599c27c862a0a27fd2c890b564edbd5f8d7", budget)
    assert evidence2["cached"] is True and provider.calls == 1
    assert spec2 == spec


def test_budget_abort():
    provider = FakeProvider(GOOD_STRIPE)
    budget = BudgetTracker(cap_usd=0.0)
    completion = Completion(text="{}", model="m", cost_usd=0.01)
    with pytest.raises(BudgetExceeded):
        budget.add(completion)
    assert provider.calls == 0


def test_token_cap_binds_on_free_tier(tmp_path):
    # Reported cost is 0.0 on the free tier; the token cap must abort.
    provider = FakeProvider(GOOD_STRIPE)
    budget = BudgetTracker(cap_usd=20, cap_tokens=10)
    with pytest.raises(BudgetExceeded):
        proposer.propose(
            provider, "fake", "7ec2459", "stripe.products.create",
            _context(), [], tmp_path,
            "7ec24599c27c862a0a27fd2c890b564edbd5f8d7", budget)
    assert provider.calls == 1  # spend recorded, then abort
    assert budget.tokens > 10


def test_budget_precheck_refuses_call_when_exhausted(tmp_path):
    provider = FakeProvider(GOOD_STRIPE)
    budget = BudgetTracker(cap_usd=20, cap_tokens=0, tokens=1)
    with pytest.raises(BudgetExceeded):
        proposer.propose(
            provider, "fake", "7ec2459", "stripe.products.create",
            _context(), [], tmp_path,
            "7ec24599c27c862a0a27fd2c890b564edbd5f8d7", budget)
    assert provider.calls == 0  # no API call on an exhausted budget


def test_cache_key_tracks_prompt_content(tmp_path):
    provider = FakeProvider(GOOD_STRIPE)
    budget = BudgetTracker(cap_usd=20)
    commit = "7ec24599c27c862a0a27fd2c890b564edbd5f8d7"
    proposer.propose(provider, "fake", "7ec2459", "stripe.products.create",
                     _context(), [], tmp_path, commit, budget)
    assert provider.calls == 1
    # Same prompt reparses from cache; changed examples miss the cache.
    proposer.propose(provider, "fake", "7ec2459", "stripe.products.create",
                     _context(), [], tmp_path, commit, budget)
    assert provider.calls == 1
    other = dict(GOOD_STRIPE, id="stripe.coupons.list")
    proposer.propose(provider, "fake", "7ec2459", "stripe.products.create",
                     _context(), [other], tmp_path, commit, budget)
    assert provider.calls == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_build_prompt_refilters_holdout_examples():
    prompt = proposer.build_prompt("7ec", _context(), [GOOD_STRIPE])
    assert "stripe.products.create" not in prompt  # hold-out (H-065)


def test_prompt_is_deterministic_and_versioned():
    a = proposer.build_prompt("7ec", _context(), [])
    b = proposer.build_prompt("7ec", _context(), [])
    assert a == b and "prompt v1" in a


def test_holdout_excluded_from_examples(tmp_path):
    (tmp_path / "s.yaml").write_text(yaml.safe_dump(GOOD_STRIPE))
    other = dict(GOOD_STRIPE, id="stripe.coupons.list")
    (tmp_path / "o.yaml").write_text(yaml.safe_dump(other))
    examples = proposer.load_examples([tmp_path])
    ids = [e["id"] for e in examples]
    assert "stripe.products.create" not in ids  # hold-out (H-065)
    assert "stripe.coupons.list" in ids


def test_validator_accepts_good_proposal():
    assert validator.check_one(GOOD_STRIPE, KNOWN) == []


def test_validator_rejects_blocked_resource():
    bad = copy.deepcopy(GOOD_STRIPE)
    bad["operation"] = {"method": "GET", "path": "/v1/api_keys"}
    bad["inverse"] = None
    bad["effect_class"] = "read"
    bad["fidelity"] = "exact"
    bad["before_image"] = {
        "read": {"method": "GET", "path": "/v1/api_keys",
                 "params": {}}, "fields": ["x"]}
    bad["verify"] = {"read": {"method": "GET", "path": "/v1/api_keys",
                              "params": {}},
                     "compare": {"fields": ["x"], "against": "before_image"}}
    assert any("blocked" in e for e in validator.check_one(bad))


def test_validator_rejects_unknown_operation():
    bad = copy.deepcopy(GOOD_STRIPE)
    bad["operation"] = {"method": "POST", "path": "/v1/frobnicator"}
    assert any("unknown operation" in e
               for e in validator.check_one(bad, KNOWN))


def test_validator_rejects_self_inverse():
    bad = copy.deepcopy(GOOD_STRIPE)
    bad["inverse"] = {
        "operation": {"method": "POST", "path": "/v1/products"},
        "params": {}, "body_from_before_image": []}
    assert any("self-inverse" in e for e in validator.check_one(bad, KNOWN))


def test_validator_rejects_unresolved_template():
    bad = copy.deepcopy(GOOD_STRIPE)
    bad["inverse"]["params"] = {"id": "$.session.id"}
    assert any("root" in e for e in validator.check_one(bad, KNOWN))


def test_validator_detects_pair_cycle():
    a = dict(GOOD_STRIPE, id="s.a",
             operation={"method": "POST", "path": "/v1/a"})
    a["inverse"] = {"operation": {"method": "POST", "path": "/v1/b"},
                    "params": {}, "body_from_before_image": []}
    b = dict(GOOD_STRIPE, id="s.b",
             operation={"method": "POST", "path": "/v1/b"})
    b["inverse"] = {"operation": {"method": "POST", "path": "/v1/a"},
                    "params": {}, "body_from_before_image": []}
    assert any("cycle" in e
               for e in validator.check_set({"s.a": a, "s.b": b}))
    assert validator.check_set({"s.a": a}) == []


def test_proposed_spec_also_passes_loader_rules():
    # Static acceptance must imply loader acceptance (no double standard).
    assert spec_loader.validate(GOOD_STRIPE, KNOWN) == []
    assert json.dumps(GOOD_STRIPE)  # cache-serializable


class _StubSystem:
    """Scripted client: (method, path) -> (code, body) or exception."""

    def __init__(self, script):
        self.script = script
        self.calls = []

    def request(self, method, path, params):
        self.calls.append((method, path, params))
        action = self.script[(method, path)]
        if isinstance(action, list):
            action = action.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


_CREATE_SPEC = {
    "spec_version": 1, "id": "stripe.customers.create", "system": "stripe",
    "operation": {"method": "POST", "path": "/v1/customers"},
    "effect_class": "reversible", "fidelity": "exact",
    "before_image": None,
    "produces": [{"name": "customer_id", "from": "$.response.id"}],
    "inverse": {
        "operation": {"method": "DELETE",
                      "path": "/v1/customers/{customer}"},
        "params": {"customer": "$.produced.customer_id"},
        "body_from_before_image": []},
    "verify": {
        "read": {"method": "GET", "path": "/v1/customers/cus_x",
                 "params": {}},
        "compare": {"fields": [], "against": "before_image"}},
}


def test_failed_trial_still_runs_cleanup():
    client = _StubSystem({("POST", "/v1/customers"): (500, {"error": "x"})})
    result = verifier.run_trial(client, _CREATE_SPEC)
    assert result["outcome"] == "fixture_unavailable"
    # The finally-cleanup ran and recorded its (empty) notes.
    assert result["evidence"]["cleanup"] == []
    assert [(m, p) for m, p, _ in client.calls] == [("POST", "/v1/customers")]


def test_successful_trial_deletes_fixture_object():
    client = _StubSystem({
        ("POST", "/v1/customers"): (200, {"id": "cus_x"}),
        ("DELETE", "/v1/customers/cus_x"): (200, {}),
        ("GET", "/v1/customers/cus_x"): (404, {"error": "gone"}),
    })
    result = verifier.run_trial(client, _CREATE_SPEC)
    assert result["outcome"] == "verified_exact"
    assert ("DELETE", "/v1/customers/cus_x", {}) in client.calls
    assert result["evidence"]["cleanup"] == []


def test_update_cleanup_deletes_fixture_customer():
    client = _StubSystem({("DELETE", "/v1/customers/cus_u"): (200, {})})
    spec = dict(_CREATE_SPEC, id="stripe.customers.update")
    notes = verifier._cleanup(client, spec, {}, {"customer": "cus_u"})
    assert notes == []
    assert ("DELETE", "/v1/customers/cus_u", {}) in client.calls


_UPDATE_SPEC = {
    "spec_version": 1, "id": "stripe.customers.update", "system": "stripe",
    "operation": {"method": "POST", "path": "/v1/customers/cus_u"},
    "effect_class": "reversible", "fidelity": "exact",
    "before_image": {
        "read": {"method": "GET", "path": "/v1/customers/cus_u",
                 "params": {}},
        "fields": ["name"]},
    "produces": [],
    "inverse": {
        "operation": {"method": "POST", "path": "/v1/customers/cus_u"},
        "params": {},
        "body_from_before_image": ["name"]},
    "verify": {
        "read": {"method": "GET", "path": "/v1/customers/cus_u",
                 "params": {}},
        "compare": {"fields": ["name"], "against": "before_image"}},
}


def test_attempt_restores_before_image_fields():
    # Full update cycle offline: the inverse must carry the before-image
    # fields (regression: a dropped `before` assignment fails every
    # update trial with "inverse unresolvable").
    client = _StubSystem({
        ("GET", "/v1/customers/cus_u"): [(200, {"name": "Pre"}),
                                         (200, {"name": "Pre"})],
        ("POST", "/v1/customers/cus_u"): [(200, {"name": "Post"}),
                                          (200, {})],
    })
    result, args, produced = verifier._attempt(
        client, _UPDATE_SPEC, lambda c, s: {"customer": "cus_u"})
    assert result["outcome"] == "verified_exact", result
    posts = [c for c in client.calls if c[0] == "POST"]
    assert posts[1][2] == {"name": "Pre"}


def test_confirm_cleanup_cancels_open_intent_only():
    spec = dict(_CREATE_SPEC, id="stripe.payment_intents.confirm")
    open_client = _StubSystem({
        ("GET", "/v1/payment_intents/pi_open"):
            (200, {"id": "pi_open", "status": "requires_confirmation"}),
        ("POST", "/v1/payment_intents/pi_open/cancel"): (200, {}),
    })
    assert verifier._cleanup(open_client, spec, {},
                             {"intent": "pi_open"}) == []
    assert ("POST", "/v1/payment_intents/pi_open/cancel", {}) \
        in open_client.calls
    # A moved-on intent (refunded) is left alone, quietly.
    done_client = _StubSystem({
        ("GET", "/v1/payment_intents/pi_done"):
            (200, {"id": "pi_done", "status": "succeeded"}),
    })
    assert verifier._cleanup(done_client, spec, {},
                             {"intent": "pi_done"}) == []
    assert len(done_client.calls) == 1
