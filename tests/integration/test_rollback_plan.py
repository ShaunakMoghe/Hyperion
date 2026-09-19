"""H-022: rollback planner dry runs (live ledger, no execution)."""

import uuid

import pytest

from hyperion.executor import executor, rollback_plan

pytestmark = pytest.mark.integration


def _chain(env):
    """lead -> deal -> note plus an independent lead. Returns ids."""
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    lead = executor.execute(conn, run_id, "crm", "leads.create",
                            {"name": "Plan"}, specs=specs, clients=clients)
    deal = executor.execute(
        conn, run_id, "crm", "deals.create",
        {"lead_id": lead["produced"]["lead_id"], "title": "D"},
        specs=specs, clients=clients, declared_deps=[lead["call_id"]])
    note = executor.execute(
        conn, run_id, "crm", "notes.add",
        {"deal_id": deal["produced"]["deal_id"], "body": "n"},
        specs=specs, clients=clients, declared_deps=[deal["call_id"]])
    indep = executor.execute(conn, run_id, "crm", "leads.create",
                             {"name": "Indep"}, specs=specs, clients=clients)
    return {"lead": lead["call_id"], "deal": deal["call_id"],
            "note": note["call_id"], "indep": indep["call_id"]}


def test_provenance_plan_orders_dependents_first(env):
    conn, run_id = env["conn"], env["run_id"]
    ids = _chain(env)
    the_plan = rollback_plan.plan(conn, run_id, [ids["lead"]])
    assert the_plan["status"] == "ready"
    assert [s["call_id"] for s in the_plan["steps"]] == [
        ids["note"], ids["deal"], ids["lead"]]
    assert {s["expected"] for s in the_plan["steps"]} == {
        "restored_exact", "restored_equivalent"}
    assert the_plan["untouched"] == [ids["indep"]]
    text = rollback_plan.plan_text(the_plan)
    assert "notes.add" in text and "untouched: 1" in text


def test_linear_mode_chains_predecessors(env):
    conn, run_id = env["conn"], env["run_id"]
    ids = _chain(env)
    the_plan = rollback_plan.plan(conn, run_id, [ids["lead"]], mode="linear")
    got = [s["call_id"] for s in the_plan["steps"]]
    # Linear closure from the first call covers the whole run.
    assert got == [ids["indep"], ids["note"], ids["deal"], ids["lead"]]
    assert the_plan["untouched"] == []


def test_executed_irreversible_blocks_until_forced(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    ids = _chain(env)
    to = f"plan-{uuid.uuid4().hex[:8]}@example.com"
    mail = executor.execute(
        conn, run_id, "crm", "emails.send",
        {"to": to, "subject": "S", "body": "B"},
        specs=specs, clients=clients, declared_deps=[ids["note"]])
    executor.approve_and_execute(conn, mail["call_id"], "tester",
                                 specs, clients)
    blocked = rollback_plan.plan(conn, run_id, [ids["lead"]])
    assert blocked["status"] == "blocked"
    assert [b["call_id"] for b in blocked["blocked"]] == [mail["call_id"]]
    forced = rollback_plan.plan(conn, run_id, [ids["lead"]], force=True)
    assert forced["status"] == "ready"
    assert [s["call_id"] for s in forced["steps"]][0] == mail["call_id"]
    assert forced["steps"][0]["expected"] == "skipped_irreversible"


def test_unknown_target_raises(env):
    with pytest.raises(KeyError):
        rollback_plan.plan(env["conn"], env["run_id"], ["nope"])
