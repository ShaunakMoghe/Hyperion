"""H-050/H-051: auto provenance edges land in the ledger and planner."""

import pytest

from hyperion.executor import executor, provenance, rollback_plan
from hyperion.ledger import store

pytestmark = pytest.mark.integration


def test_auto_edges_link_deal_to_lead_without_declared_deps(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    lead = executor.execute(conn, run_id, "crm", "leads.create",
                            {"name": "Prov"}, specs=specs, clients=clients)
    deal = executor.execute(
        conn, run_id, "crm", "deals.create",
        {"lead_id": lead["produced"]["lead_id"], "title": "P"},
        specs=specs, clients=clients)  # no declared_deps on purpose
    rows = conn.execute(
        "SELECT depends_on_call_id, kind, evidence FROM edges "
        "WHERE call_id = %s",
        (deal["call_id"],)).fetchall()
    assert len(rows) == 1
    dep, kind, evidence = rows[0]
    assert str(dep) == lead["call_id"] and kind == "provenance"
    assert evidence["args_path"] == "$.args.lead_id"
    assert evidence["response_path"] == "$.response.id"


def test_planner_uses_auto_edges(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    lead = executor.execute(conn, run_id, "crm", "leads.create",
                            {"name": "PP"}, specs=specs, clients=clients)
    deal = executor.execute(
        conn, run_id, "crm", "deals.create",
        {"lead_id": lead["produced"]["lead_id"], "title": "P"},
        specs=specs, clients=clients)
    the_plan = rollback_plan.plan(conn, run_id, [lead["call_id"]])
    assert [s["call_id"] for s in the_plan["steps"]] == [deal["call_id"],
                                                         lead["call_id"]]


def test_link_call_is_idempotent(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    lead = executor.execute(conn, run_id, "crm", "leads.create",
                            {"name": "Idem"}, specs=specs, clients=clients)
    deal = executor.execute(
        conn, run_id, "crm", "deals.create",
        {"lead_id": lead["produced"]["lead_id"], "title": "P"},
        specs=specs, clients=clients, auto_provenance=False)
    first = provenance.link_call(conn, run_id, deal["call_id"], specs)
    second = provenance.link_call(conn, run_id, deal["call_id"], specs)
    assert len(first) == 1 and second == []
    assert store.verify_chain(conn, run_id)["ok"] is True
