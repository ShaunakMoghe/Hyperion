"""H-013: mini-CRM behavior against real Postgres (ASGI transport, no mocks)."""

import pytest
from fastapi.testclient import TestClient
from targets.crm import db as crm_db
from targets.crm.app import create_app

from hyperion.config import load
from hyperion.ledger import db

pytestmark = pytest.mark.integration


@pytest.fixture()
def client():
    conn = db.connect(load())
    db.migrate_up(conn)
    conn.close()
    crm_db.migrate_up()
    with TestClient(create_app()) as c:
        yield c
    # Leave data in place: per-test ids are unique; snapshot tests compare
    # within a single test only.


def test_create_lead_returns_server_id(client):
    r = client.post("/leads", json={"name": "Ada"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] and body["id"] != "lead_999"  # not client-supplied
    assert body["name"] == "Ada"


def test_deal_uses_returned_lead_id_and_note_attaches(client):
    lead = client.post("/leads", json={"name": "Grace"}).json()
    deal = client.post(
        "/deals", json={"lead_id": lead["id"], "title": "Big", "amount_cents": 500}
    ).json()
    assert deal["lead_id"] == lead["id"]
    note = client.post(f"/deals/{deal['id']}/notes", json={"body": "hi"}).json()
    assert note["deal_id"] == deal["id"]
    notes = client.get(f"/deals/{deal['id']}/notes").json()
    assert [n["id"] for n in notes["notes"]] == [note["id"]]


def test_deal_rejects_unknown_lead(client):
    r = client.post("/deals", json={"lead_id": "00000000-0000-0000-0000-000000000000",
                                    "title": "Bad"})
    assert r.status_code == 422


def test_delete_leaves_tombstone(client):
    lead = client.post("/leads", json={"name": "Temp"}).json()
    gone = client.delete(f"/leads/{lead['id']}").json()
    assert gone["deleted_at"] is not None
    assert client.get(f"/leads/{lead['id']}").status_code == 410


def test_restore_undeletes_lead(client):
    lead = client.post("/leads", json={"name": "Back"}).json()
    client.delete(f"/leads/{lead['id']}")
    assert client.get(f"/leads/{lead['id']}").status_code == 410
    restored = client.post(f"/leads/{lead['id']}/restore").json()
    assert restored["deleted_at"] is None
    assert client.get(f"/leads/{lead['id']}").json()["name"] == "Back"


def test_restore_undeletes_deal(client):
    lead = client.post("/leads", json={"name": "D"}).json()
    deal = client.post(
        "/deals", json={"lead_id": lead["id"], "title": "T"}).json()
    client.delete(f"/deals/{deal['id']}")
    restored = client.post(f"/deals/{deal['id']}/restore").json()
    assert restored["deleted_at"] is None


def test_delete_note_removes_it(client):
    lead = client.post("/leads", json={"name": "N"}).json()
    deal = client.post(
        "/deals", json={"lead_id": lead["id"], "title": "T"}).json()
    note = client.post(f"/deals/{deal['id']}/notes", json={"body": "x"}).json()
    assert client.delete(f"/notes/{note['id']}").json()["deleted"] is True
    assert client.get(f"/deals/{deal['id']}/notes").json() == {"notes": []}


def test_snapshot_is_deterministic(client):
    first = client.get("/snapshot").content
    second = client.get("/snapshot").content
    assert first == second


def test_email_send_is_delivered_immediately(client):
    r = client.post("/emails", json={"to": "vp@example.com", "subject": "Hi",
                                     "body": "report"})
    assert r.status_code == 201
    assert r.json()["delivered_at"] is not None
