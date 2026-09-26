"""M11: saga runner (real Postgres + live CRM; one Stripe-marked test)."""

import uuid

import pytest

from hyperion.executor import rollback_exec, saga
from hyperion.ledger import store

pytestmark = pytest.mark.integration

AUTO_DEAL_POLICY = {
    "default": "allow",
    "rules": [
        {"match": {"system": "crm", "operation": "deals.create",
                   "when": "amount_cents > 100000"},
         "effect": "require_approval"},
    ],
}


def _saga_env(env):
    return env["conn"], env["run_id"], env["specs"], env["clients"]


def test_saga_completes_and_links_provenance(env):
    conn, run_id, specs, clients = _saga_env(env)
    first = saga.run_saga(conn, run_id, [
        {"system": "crm", "operation": "leads.create",
         "args": {"name": "Saga Lead"}},
    ], specs=specs, clients=clients)
    assert first["status"] == "completed"
    lead_id = first["steps"][0]["produced"]["lead_id"]
    deal_out = saga.run_saga(conn, run_id, [
        {"system": "crm", "operation": "deals.create",
         "args": {"lead_id": lead_id, "title": "Saga Deal",
                 "amount_cents": 100}},
    ], specs=specs, clients=clients)
    assert deal_out["status"] == "completed"
    deal_id = deal_out["steps"][0]["produced"]["deal_id"]
    out = saga.run_saga(conn, run_id, [
        {"system": "crm", "operation": "notes.add",
         "args": {"deal_id": deal_id, "body": "saga note"}},
    ], specs=specs, clients=clients)
    assert out["status"] == "completed"

    edges = {(e["call_id"], e["depends_on_call_id"], e["kind"])
             for e in store.list_edges(conn, run_id)}
    prov = {(c, d) for c, d, k in edges if k == "provenance"}
    calls = store.list_calls(conn, run_id)
    by_op = {c["operation"]: str(c["id"]) for c in calls}
    assert (by_op["deals.create"], by_op["leads.create"]) in prov
    assert (by_op["notes.add"], by_op["deals.create"]) in prov


def test_saga_compensates_on_failure(env):
    conn, run_id, specs, clients = _saga_env(env)
    out = saga.run_saga(conn, run_id, [
        {"system": "crm", "operation": "leads.create",
         "args": {"name": "Doomed Lead"}},
        {"system": "crm", "operation": "deals.create",
         "args": {"lead_id": "00000000-0000-0000-0000-000000000000",
                 "title": "Bad"}},
    ], specs=specs, clients=clients)
    assert out["status"] == "compensated"
    assert out["aborted_at"] == 1
    assert out["steps"][1]["status"] == "failed"
    assert set(out["compensation"]["outcomes"]) == {
        out["steps"][0]["call_id"]}
    lead_id = out["steps"][0]["produced"]["lead_id"]
    code, _ = clients["crm"].request(
        "GET", "/leads/{lead_id}", {"lead_id": lead_id})
    assert code == 410


def test_saga_compensates_on_denial(env):
    conn, run_id, specs, clients = _saga_env(env)
    out = saga.run_saga(conn, run_id, [
        {"system": "crm", "operation": "leads.create",
         "args": {"name": "Denied Saga Lead"}},
        {"system": "crm", "operation": "leads.delete",
         "args": {"lead_id": "whatever"}},
    ], specs=specs, clients=clients,
        policy={"default": "allow", "rules": [
            {"match": {"system": "crm", "operation": "leads.delete"},
             "effect": "deny"}]})
    assert out["status"] == "compensated"
    assert out["steps"][1]["status"] == "denied"
    lead_id = out["steps"][0]["produced"]["lead_id"]
    code, _ = clients["crm"].request(
        "GET", "/leads/{lead_id}", {"lead_id": lead_id})
    assert code == 410


def test_saga_awaits_approval_when_held(env):
    conn, run_id, specs, clients = _saga_env(env)
    out = saga.run_saga(conn, run_id, [
        {"system": "crm", "operation": "leads.create",
         "args": {"name": "Held Saga Lead"}},
        {"system": "crm", "operation": "deals.create",
         "args": {"lead_id": "pending", "title": "Big",
                 "amount_cents": 500000}},
    ], specs=specs, clients=clients, policy=AUTO_DEAL_POLICY)
    # Step 2's lead_id is bogus on purpose: any policy-held step pauses
    # the saga before execution, regardless of arg validity.
    assert out["status"] == "awaiting_approval"
    assert out["steps"][0]["status"] == "executed"
    assert out["steps"][1]["status"] == "held"
    assert out["compensation"] is None


def test_saga_auto_approves_and_completes(env):
    conn, run_id, specs, clients = _saga_env(env)
    first = saga.run_saga(conn, run_id, [
        {"system": "crm", "operation": "leads.create",
         "args": {"name": "Auto Saga Lead"}},
    ], specs=specs, clients=clients)
    lead_id = first["steps"][0]["produced"]["lead_id"]
    out = saga.run_saga(conn, run_id, [
        {"system": "crm", "operation": "deals.create",
         "args": {"lead_id": lead_id, "title": "Big Auto",
                 "amount_cents": 500000}},
    ], specs=specs, clients=clients, policy=AUTO_DEAL_POLICY,
        approve_held="auto")
    assert out["status"] == "completed"
    assert out["steps"][0]["status"] == "executed"


def test_saga_partial_when_irreversible_survives(env):
    conn, run_id, specs, clients = _saga_env(env)
    out = saga.run_saga(conn, run_id, [
        {"system": "crm", "operation": "emails.send",
         "args": {"to": f"saga-{uuid.uuid4().hex[:8]}@example.com",
                 "subject": "S", "body": "B"}},
        {"system": "crm", "operation": "deals.create",
         "args": {"lead_id": "00000000-0000-0000-0000-000000000000",
                 "title": "Bad"}},
    ], specs=specs, clients=clients, approve_held="auto")
    assert out["status"] == "partial"
    assert out["steps"][0]["status"] == "executed"
    assert out["compensation"]["outcomes"] == {
        out["steps"][0]["call_id"]: "skipped_irreversible"}


def test_stamp_saga_records_summary(env):
    conn, run_id = env["conn"], env["run_id"]
    store.stamp_saga(conn, run_id, {"id": "sag-x", "status": "completed"})
    assert store.get_run(conn, run_id)["meta"]["saga"] == {
        "id": "sag-x", "status": "completed"}


@pytest.mark.stripe
def test_saga_cross_system_compensation(env):
    conn, run_id, specs, clients = _saga_env(env)
    email = f"saga-{uuid.uuid4().hex[:8]}@example.com"
    out = saga.run_saga(conn, run_id, [
        {"system": "crm", "operation": "leads.create",
         "args": {"name": "X-Lead", "email": email}},
        {"system": "stripe", "operation": "customers.create",
         "args": {"name": "X-Customer", "email": email}},
    ], specs=specs, clients=clients)
    assert out["status"] == "completed"
    lead_call, cust_call = (s["call_id"] for s in out["steps"])
    edges = {(e["call_id"], e["depends_on_call_id"])
             for e in store.list_edges(conn, run_id)}
    assert (cust_call, lead_call) in edges  # shared email spans systems

    rb = rollback_exec.start(conn, run_id, [cust_call, lead_call],
                             clients=clients, specs=specs)
    assert rb["status"] == "completed"
    assert set(rb["outcomes"].values()) <= saga.RESTORED
