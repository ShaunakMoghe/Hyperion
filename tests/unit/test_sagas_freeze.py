"""M11: saga freeze validation (offline: yaml + op ids only)."""

from pathlib import Path

import yaml
from bench.freeze_sagas import validate_sagas

REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = {"crm.leads.create", "crm.deals.create", "stripe.customers.create"}


def _doc():
    return yaml.safe_load(
        (REPO_ROOT / "bench/scenarios/sagas.yaml").read_text(
            encoding="utf-8"))


def _op_ids():
    ids = set()
    for path in (REPO_ROOT / "specs").rglob("*.yaml"):
        ids.add(yaml.safe_load(path.read_text(encoding="utf-8"))["id"])
    return ids


def test_shipped_sagas_validate_clean():
    assert validate_sagas(_doc(), _op_ids()) == []


def _saga(**over):
    sg = {"id": "sag-x", "approvals": "auto", "expect_saga": "completed",
          "expect_rollback": "clean", "policy": None,
          "steps": [{"system": "crm", "op": "leads.create", "args": {}}]}
    sg.update(over)
    return {"sagas": [sg]}


def test_duplicate_ids_rejected():
    doc = {"sagas": [_saga()["sagas"][0], _saga()["sagas"][0]]}
    errors = validate_sagas(doc, OPS)
    assert any("duplicate" in e for e in errors)


def test_unknown_op_rejected():
    doc = _saga(steps=[{"system": "crm", "op": "nope.delete", "args": {}}])
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, OPS)
    assert any("unknown op" in e for e in errors)


def test_bad_ref_rejected():
    doc = _saga(steps=[
        {"system": "crm", "op": "leads.create", "args": {}},
        {"system": "crm", "op": "deals.create",
         "args": {"lead_id": {"$ref": [5, "lead_id"]}}}])
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, OPS)
    assert any("bad $ref" in e for e in errors)


def test_bad_policy_rejected():
    doc = _saga(policy={"default": "sometimes", "rules": []})
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, OPS)
    assert any("bad policy" in e for e in errors)


def test_bad_saga_status_rejected():
    doc = _saga(expect_saga="transmuted")
    errors = validate_sagas({"sagas": [doc["sagas"][0]]}, OPS)
    assert any("expect_saga" in e for e in errors)
