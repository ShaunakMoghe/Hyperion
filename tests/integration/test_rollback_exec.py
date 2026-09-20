"""H-023 (a, c): verified restoration and drift conflicts (live CRM)."""

import pytest

from hyperion.executor import executor, rollback_exec
from hyperion.ledger import store

pytestmark = pytest.mark.integration


def _chain(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    lead = executor.execute(conn, run_id, "crm", "leads.create",
                            {"name": "R"}, specs=specs, clients=clients)
    upd = executor.execute(
        conn, run_id, "crm", "leads.update",
        {"lead_id": lead["produced"]["lead_id"], "name": "Renamed"},
        specs=specs, clients=clients, declared_deps=[lead["call_id"]])
    deal = executor.execute(
        conn, run_id, "crm", "deals.create",
        {"lead_id": lead["produced"]["lead_id"], "title": "D"},
        specs=specs, clients=clients, declared_deps=[upd["call_id"]])
    return {"lead": lead, "upd": upd, "deal": deal}


def test_verified_restoration_on_crm(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    ids = _chain(env)
    lead_id = ids["lead"]["produced"]["lead_id"]
    out = rollback_exec.start(conn, run_id, [ids["lead"]["call_id"]],
                              clients=clients, specs=specs)
    assert out["status"] == "completed"
    assert set(out["outcomes"].values()) == {"restored_equivalent",
                                             "restored_exact"}
    # Lead + deal tombstoned, update restored then tombstoned with the lead.
    code, lead = clients["crm"].request("GET", "/leads/{lead_id}",
                                        {"lead_id": lead_id})
    assert code == 410
    for cid in (ids["lead"]["call_id"], ids["upd"]["call_id"],
                ids["deal"]["call_id"]):
        assert store.get_call(conn, cid)["status"] == "rolled_back"


def test_concurrent_modification_yields_conflict_and_skips(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    ids = _chain(env)
    deal_id = ids["deal"]["produced"]["deal_id"]
    lead_id = ids["lead"]["produced"]["lead_id"]
    # External actor retitles the deal behind the ledger's back.
    clients["crm"].request("PATCH", "/deals/{deal_id}",
                           {"deal_id": deal_id, "title": "Intruder"})
    out = rollback_exec.start(conn, run_id, [ids["lead"]["call_id"]],
                              clients=clients, specs=specs)
    assert out["status"] == "completed"
    assert out["outcomes"][ids["deal"]["call_id"]] == "conflict_detected"
    assert store.get_call(conn, ids["deal"]["call_id"])["status"] == "conflict"
    # The deal inverse never ran: the intruder's title stands, deal live.
    code, deal = clients["crm"].request("GET", "/deals/{deal_id}",
                                        {"deal_id": deal_id})
    assert code == 200
    assert deal["title"] == "Intruder"
    # Lead and update are untouched by deal-level drift: both restored.
    assert out["outcomes"][ids["upd"]["call_id"]] == "restored_exact"
    assert out["outcomes"][ids["lead"]["call_id"]] == "restored_equivalent"
    code, lead = clients["crm"].request("GET", "/leads/{lead_id}",
                                        {"lead_id": lead_id})
    assert code == 410


def test_read_call_rolls_back_as_skipped_read(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    lead = executor.execute(conn, run_id, "crm", "leads.create",
                            {"name": "R"}, specs=specs, clients=clients)
    read = executor.execute(
        conn, run_id, "crm", "leads.read",
        {"lead_id": lead["produced"]["lead_id"]},
        specs=specs, clients=clients, declared_deps=[lead["call_id"]])
    out = rollback_exec.start(conn, run_id, [lead["call_id"]],
                              clients=clients, specs=specs)
    assert out["status"] == "completed"
    # Reads take no effect: skipped, never inverted (inverse is null).
    assert out["outcomes"][read["call_id"]] == "skipped_read"
    assert out["outcomes"][lead["call_id"]] == "restored_equivalent"
    assert store.get_call(conn, read["call_id"])["status"] == "rolled_back"
