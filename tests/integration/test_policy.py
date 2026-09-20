"""H-052: policy wiring in the executor (live ledger, real CRM)."""

import pytest
import yaml

from hyperion.executor import approvals, executor
from hyperion.ledger import store

pytestmark = pytest.mark.integration


def _write(tmp_path, body: dict) -> str:
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(body))
    return str(path)


def test_missing_policy_file_denies(env, tmp_path):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    out = executor.execute(conn, run_id, "crm", "leads.read",
                           {"lead_id": "x"}, specs=specs, clients=clients,
                           policy_path=str(tmp_path / "absent.yaml"))
    assert out["status"] == "denied"
    assert "policy" in out["reason"]


def test_malformed_args_denied(env, tmp_path):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    path = _write(tmp_path, {"default": "allow", "rules": []})
    out = executor.execute(conn, run_id, "crm", "leads.read", "nope",
                           specs=specs, clients=clients, policy_path=path)
    assert out["status"] == "denied"


def test_deny_rule_blocks(env, tmp_path):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    path = _write(tmp_path, {
        "default": "allow",
        "rules": [{"match": {"system": "crm", "operation": "leads.create"},
                   "effect": "deny"}]})
    out = executor.execute(conn, run_id, "crm", "leads.create",
                           {"name": "N"}, specs=specs, clients=clients,
                           policy_path=path)
    assert out["status"] == "denied"
    assert store.get_call(conn, out["call_id"])["status"] == "blocked"


def test_over_threshold_held_then_approved_once(env, tmp_path):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    path = _write(tmp_path, {
        "default": "allow",
        "rules": [{"match": {"system": "crm", "operation": "deals.create",
                             "when": "amount_cents > 100000"},
                   "effect": "require_approval"}]})
    lead = executor.execute(conn, run_id, "crm", "leads.create",
                            {"name": "Pol"}, specs=specs, clients=clients,
                            policy_path=path)
    assert lead["status"] == "executed"
    deal = executor.execute(
        conn, run_id, "crm", "deals.create",
        {"lead_id": lead["produced"]["lead_id"], "title": "Big",
         "amount_cents": 500000},
        specs=specs, clients=clients, policy_path=path)
    assert deal["status"] == "held"
    assert deal["result"] == approvals.PENDING
    # Same call id executes exactly once through the finalize path.
    done = executor.approve_and_execute(conn, deal["call_id"], "tester",
                                        specs, clients)
    assert done["status"] == "executed"
    assert done["call_id"] == deal["call_id"]
    row = store.get_call(conn, deal["call_id"])
    assert row["status"] == "executed"
    assert row["response"]["amount_cents"] == 500000
    assert row["before_image"] is None  # create-style
    assert store.verify_chain(conn, run_id)["ok"] is True


def test_allowlist_default_deny(env, tmp_path):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    path = _write(tmp_path, {
        "default": "deny",
        "rules": [{"match": {"system": "crm", "operation": "leads.read"},
                   "effect": "allow"}]})
    lead = executor.execute(conn, run_id, "crm", "leads.create",
                            {"name": "AL"}, specs=specs, clients=clients,
                            policy_path=path)
    assert lead["status"] == "denied"  # not allowlisted
    plain = executor.execute(conn, run_id, "crm", "leads.create",
                             {"name": "AL2"}, specs=specs, clients=clients)
    assert plain["status"] == "executed"
    read = executor.execute(conn, run_id, "crm", "leads.read",
                            {"lead_id": plain["produced"]["lead_id"]},
                            specs=specs, clients=clients, policy_path=path)
    assert read["status"] == "executed"  # allowlisted
    unknown = executor.execute(conn, run_id, "crm", "snapshot", {},
                               specs=specs, clients=clients, policy_path=path)
    assert unknown["status"] == "denied"  # unknown op still denied
