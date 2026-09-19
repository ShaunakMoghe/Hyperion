"""H-024: canonical e2e scenario (no mocks).

Sequence: create lead -> create deal (lead id from response) -> add note ->
hold email -> fault -> rollback. Plus an independent legitimate action that
must survive. Real Postgres, real CRM over HTTP.
"""

import pytest

from hyperion.executor import approvals, executor, rollback_exec
from hyperion.ledger import store

pytestmark = pytest.mark.e2e


def _snapshot(clients):
    code, body = clients["crm"].request("GET", "/snapshot", {})
    assert code == 200
    return body


def test_canonical_scenario(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    before = _snapshot(clients)
    before_lead_ids = {lead["id"] for lead in before["leads"]}
    before_deal_ids = {d["id"] for d in before["deals"]}

    lead = executor.execute(conn, run_id, "crm", "leads.create",
                            {"name": "E2E"}, specs=specs, clients=clients)
    deal = executor.execute(
        conn, run_id, "crm", "deals.create",
        {"lead_id": lead["produced"]["lead_id"], "title": "E2E deal"},
        specs=specs, clients=clients, declared_deps=[lead["call_id"]])
    note = executor.execute(
        conn, run_id, "crm", "notes.add",
        {"deal_id": deal["produced"]["deal_id"], "body": "E2E note"},
        specs=specs, clients=clients, declared_deps=[deal["call_id"]])
    mail = executor.execute(
        conn, run_id, "crm", "emails.send",
        {"to": "e2e-vp@example.com", "subject": "S", "body": "B"},
        specs=specs, clients=clients, declared_deps=[note["call_id"]])
    assert mail["result"] == approvals.PENDING

    # Independent legitimate action: no dependency edges at all.
    indep = executor.execute(conn, run_id, "crm", "leads.create",
                             {"name": "Bystander"}, specs=specs, clients=clients)

    # Fault: a deal for a nonexistent lead fails.
    fault = executor.execute(
        conn, run_id, "crm", "deals.create",
        {"lead_id": "00000000-0000-0000-0000-000000000000", "title": "Fault"},
        specs=specs, clients=clients, declared_deps=[note["call_id"]])
    assert fault["status"] == "failed"

    out = rollback_exec.start(conn, run_id, [lead["call_id"]],
                              clients=clients, specs=specs)
    assert out["status"] == "completed"
    assert set(out["outcomes"]) == {lead["call_id"], deal["call_id"],
                                    note["call_id"]}

    after = _snapshot(clients)

    # Pre-existing rows byte-identical.
    for table, ids in (("leads", before_lead_ids), ("deals", before_deal_ids)):
        old = {r["id"]: r for r in before[table]}
        new = {r["id"]: r for r in after[table]}
        for oid in ids:
            assert new[oid] == old[oid], (table, oid)

    # Scenario rows: lead + deal tombstoned, note gone.
    lead_rows = {r["id"]: r for r in after["leads"]}
    assert lead_rows[lead["produced"]["lead_id"]]["deleted_at"] is not None
    deal_rows = {r["id"]: r for r in after["deals"]}
    assert deal_rows[deal["produced"]["deal_id"]]["deleted_at"] is not None
    assert note["produced"]["note_id"] not in {
        n["id"] for n in after["notes"]}

    # Independent action survived, live.
    assert lead_rows[indep["produced"]["lead_id"]]["deleted_at"] is None
    code, live = clients["crm"].request(
        "GET", "/leads/{lead_id}",
        {"lead_id": indep["produced"]["lead_id"]})
    assert code == 200 and live["name"] == "Bystander"

    # Email never delivered; approval still pending.
    assert [e for e in after["emails_outbox"]
            if e["to_addr"] == "e2e-vp@example.com"] == []
    assert store.get_call(conn, mail["call_id"])["status"] == "held"
