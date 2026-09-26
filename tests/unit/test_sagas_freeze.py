"""M11: saga freeze validation (offline: yaml + specs only)."""

from pathlib import Path

import yaml
from bench.freeze_sagas import check_freeze, validate_sagas

REPO_ROOT = Path(__file__).resolve().parents[2]
SPECS = {
    "crm.leads.create": {"produces": [{"name": "lead_id"}]},
    "crm.deals.create": {"produces": [{"name": "deal_id"}]},
    "stripe.customers.create": {"produces": [{"name": "customer_id"}]},
}


def _doc():
    return yaml.safe_load(
        (REPO_ROOT / "bench/scenarios/sagas.yaml").read_text(
            encoding="utf-8"))


def _specs():
    specs = {}
    for path in (REPO_ROOT / "specs").rglob("*.yaml"):
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        specs[spec["id"]] = spec
    return specs


def test_shipped_sagas_validate_clean():
    assert validate_sagas(_doc(), _specs()) == []


def test_shipped_tree_matches_freeze():
    assert check_freeze() == []


def _saga(**over):
    sg = {"id": "sag-x", "approvals": "auto", "expect_saga": "completed",
          "expect_rollback": "clean", "policy": None,
          "steps": [{"system": "crm", "op": "leads.create", "args": {}}]}
    sg.update(over)
    return {"sagas": [sg]}


def test_duplicate_ids_rejected():
    doc = {"sagas": [_saga()["sagas"][0], _saga()["sagas"][0]]}
    errors = validate_sagas(doc, SPECS)
    assert any("duplicate" in e for e in errors)


def test_unknown_op_rejected():
    doc = _saga(steps=[{"system": "crm", "op": "nope.delete", "args": {}}])
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, SPECS)
    assert any("unknown op" in e for e in errors)


def test_bad_ref_index_rejected():
    doc = _saga(steps=[
        {"system": "crm", "op": "leads.create", "args": {}},
        {"system": "crm", "op": "deals.create",
         "args": {"lead_id": {"$ref": [5, "lead_id"]}}}])
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, SPECS)
    assert any("bad $ref" in e for e in errors)


def test_bad_ref_name_rejected():
    doc = _saga(steps=[
        {"system": "crm", "op": "leads.create", "args": {}},
        {"system": "crm", "op": "deals.create",
         "args": {"lead_id": {"$ref": [0, "customer_id"]}}}])
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, SPECS)
    assert any("unknown produced name" in e for e in errors)


def test_ref_to_failed_step_rejected():
    doc = _saga(steps=[
        {"system": "crm", "op": "leads.create", "args": {},
         "expect": "failed"},
        {"system": "crm", "op": "deals.create",
         "args": {"lead_id": {"$ref": [0, "lead_id"]}}}])
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, SPECS)
    assert any("produces nothing" in e for e in errors)


def test_bad_policy_rejected():
    doc = _saga(policy={"default": "sometimes", "rules": []})
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, SPECS)
    assert any("bad policy" in e for e in errors)


def test_bad_saga_status_rejected():
    doc = _saga(expect_saga="transmuted")
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, SPECS)
    assert any("expect_saga" in e for e in errors)


def test_deny_approvals_rejected():
    doc = _saga(approvals="deny")
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, SPECS)
    assert any("deny unsupported" in e for e in errors)


def test_empty_steps_rejected():
    doc = _saga(steps=[])
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, SPECS)
    assert any("no steps" in e for e in errors)


def test_approve_without_held_rejected():
    doc = _saga(steps=[{"system": "crm", "op": "leads.create", "args": {},
                        "approve": True}])
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, SPECS)
    assert any("expect held" in e for e in errors)


def test_incoherent_expects_rejected():
    doc = _saga(expect_saga="completed", expect_rollback="partial")
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, SPECS)
    assert any("contradicts" in e for e in errors)
