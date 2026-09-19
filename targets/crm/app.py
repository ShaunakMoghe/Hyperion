"""Mini-CRM target system (H-013).

FastAPI + Postgres (`crm` schema). Server-generated UUIDs: created object IDs
exist only in responses, which is why the ledger must capture them (v1 did not).
Deletes leave tombstones (`deleted_at`); notes delete hard; sending email
writes a delivered row and is irreversible.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg
import psycopg.rows
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from hyperion.config import load

from . import db as crm_db


class LeadIn(BaseModel):
    name: str
    email: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LeadPatch(BaseModel):
    name: str | None = None
    email: str | None = None
    metadata: dict[str, Any] | None = None


class DealIn(BaseModel):
    lead_id: str
    title: str
    amount_cents: int = 0
    stage: str = "open"


class DealPatch(BaseModel):
    title: str | None = None
    amount_cents: int | None = None
    stage: str | None = None


class NoteIn(BaseModel):
    body: str


class EmailIn(BaseModel):
    to_addr: str = Field(alias="to")
    subject: str
    body: str

    model_config = {"populate_by_name": True}


def _conn() -> psycopg.Connection:
    conn = psycopg.connect(load().database_url, autocommit=True)
    conn.row_factory = psycopg.rows.dict_row
    return conn


def _row_to_json(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = str(v) if isinstance(v, uuid.UUID) else v
    return out


def create_app() -> FastAPI:
    app = FastAPI(title="Hyperion mini-CRM")

    def _get(table: str, obj_id: str) -> dict:
        with _conn() as conn:
            row = conn.execute(
                f"SELECT * FROM {table} WHERE id = %s", (obj_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown id {obj_id}")
        row = _row_to_json(dict(row))
        if row.get("deleted_at") is not None:
            raise HTTPException(status_code=410, detail={"deleted": True, **row})
        return row

    @app.post("/leads", status_code=201)
    def create_lead(body: LeadIn) -> dict:
        obj_id = str(uuid.uuid4())
        with _conn() as conn:
            conn.execute(
                "INSERT INTO crm.leads (id, name, email, metadata) "
                "VALUES (%s, %s, %s, %s)",
                (obj_id, body.name, body.email, json.dumps(body.metadata)),
            )
        return _get("crm.leads", obj_id)

    @app.get("/leads/{lead_id}")
    def get_lead(lead_id: str) -> dict:
        return _get("crm.leads", lead_id)

    @app.patch("/leads/{lead_id}")
    def patch_lead(lead_id: str, body: LeadPatch) -> dict:
        current = _get("crm.leads", lead_id)
        name = body.name if body.name is not None else current["name"]
        email = body.email if body.email is not None else current["email"]
        metadata = body.metadata if body.metadata is not None else current["metadata"]
        with _conn() as conn:
            conn.execute(
                "UPDATE crm.leads SET name = %s, email = %s, metadata = %s "
                "WHERE id = %s",
                (name, email, json.dumps(metadata), lead_id),
            )
        return _get("crm.leads", lead_id)

    @app.delete("/leads/{lead_id}")
    def delete_lead(lead_id: str) -> dict:
        _get("crm.leads", lead_id)
        with _conn() as conn:
            row = conn.execute(
                "UPDATE crm.leads SET deleted_at = now() WHERE id = %s "
                "RETURNING *",
                (lead_id,),
            ).fetchone()
        return _row_to_json(dict(row))

    @app.post("/leads/{lead_id}/restore")
    def restore_lead(lead_id: str) -> dict:
        with _conn() as conn:
            row = conn.execute(
                "UPDATE crm.leads SET deleted_at = NULL WHERE id = %s "
                "RETURNING *",
                (lead_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown id {lead_id}")
        return _row_to_json(dict(row))

    @app.post("/deals", status_code=201)
    def create_deal(body: DealIn) -> dict:
        try:
            _get("crm.leads", body.lead_id)
        except HTTPException as e:
            raise HTTPException(
                status_code=422, detail=f"lead {body.lead_id}: {e.detail}"
            ) from e
        if body.amount_cents < 0:
            raise HTTPException(status_code=422, detail="amount_cents >= 0")
        obj_id = str(uuid.uuid4())
        with _conn() as conn:
            conn.execute(
                "INSERT INTO crm.deals (id, lead_id, title, amount_cents, stage) "
                "VALUES (%s, %s, %s, %s, %s)",
                (obj_id, body.lead_id, body.title, body.amount_cents, body.stage),
            )
        return _get("crm.deals", obj_id)

    @app.get("/deals/{deal_id}")
    def get_deal(deal_id: str) -> dict:
        return _get("crm.deals", deal_id)

    @app.patch("/deals/{deal_id}")
    def patch_deal(deal_id: str, body: DealPatch) -> dict:
        current = _get("crm.deals", deal_id)
        title = body.title if body.title is not None else current["title"]
        amount = (
            body.amount_cents
            if body.amount_cents is not None
            else current["amount_cents"]
        )
        stage = body.stage if body.stage is not None else current["stage"]
        if amount < 0:
            raise HTTPException(status_code=422, detail="amount_cents >= 0")
        with _conn() as conn:
            conn.execute(
                "UPDATE crm.deals SET title = %s, amount_cents = %s, stage = %s "
                "WHERE id = %s",
                (title, amount, stage, deal_id),
            )
        return _get("crm.deals", deal_id)

    @app.delete("/deals/{deal_id}")
    def delete_deal(deal_id: str) -> dict:
        _get("crm.deals", deal_id)
        with _conn() as conn:
            row = conn.execute(
                "UPDATE crm.deals SET deleted_at = now() WHERE id = %s "
                "RETURNING *",
                (deal_id,),
            ).fetchone()
        return _row_to_json(dict(row))

    @app.post("/deals/{deal_id}/restore")
    def restore_deal(deal_id: str) -> dict:
        with _conn() as conn:
            row = conn.execute(
                "UPDATE crm.deals SET deleted_at = NULL WHERE id = %s "
                "RETURNING *",
                (deal_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown id {deal_id}")
        return _row_to_json(dict(row))

    @app.post("/deals/{deal_id}/notes", status_code=201)
    def add_note(deal_id: str, body: NoteIn) -> dict:
        _get("crm.deals", deal_id)
        note_id = str(uuid.uuid4())
        with _conn() as conn:
            row = conn.execute(
                "INSERT INTO crm.notes (id, deal_id, body) VALUES (%s, %s, %s) "
                "RETURNING *",
                (note_id, deal_id, body.body),
            ).fetchone()
        return _row_to_json(dict(row))

    @app.get("/deals/{deal_id}/notes")
    def list_notes(deal_id: str) -> dict:
        _get("crm.deals", deal_id)
        with _conn() as conn:
            rows = conn.execute(
                "SELECT * FROM crm.notes WHERE deal_id = %s", (deal_id,)
            ).fetchall()
        return {"notes": [_row_to_json(dict(r)) for r in rows]}

    @app.get("/notes/{note_id}")
    def get_note(note_id: str) -> dict:
        with _conn() as conn:
            row = conn.execute(
                "SELECT * FROM crm.notes WHERE id = %s", (note_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown id {note_id}")
        return _row_to_json(dict(row))

    @app.delete("/notes/{note_id}")
    def delete_note(note_id: str) -> dict:
        with _conn() as conn:
            row = conn.execute(
                "DELETE FROM crm.notes WHERE id = %s RETURNING *", (note_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown id {note_id}")
        return {"id": note_id, "deleted": True}

    @app.post("/emails", status_code=201)
    def send_email(body: EmailIn) -> dict:
        """Irreversible: the stored row IS the delivery."""
        obj_id = str(uuid.uuid4())
        with _conn() as conn:
            row = conn.execute(
                "INSERT INTO crm.emails_outbox (id, to_addr, subject, body) "
                "VALUES (%s, %s, %s, %s) RETURNING *",
                (obj_id, body.to_addr, body.subject, body.body),
            ).fetchone()
        return _row_to_json(dict(row))

    @app.get("/snapshot")
    def snapshot() -> Response:
        """Canonical, sorted JSON of all CRM state for diffing."""
        with _conn() as conn:
            tables = {}
            for table in ("leads", "deals", "notes", "emails_outbox"):
                rows = conn.execute(f"SELECT * FROM crm.{table}").fetchall()
                tables[table] = sorted(
                    (_row_to_json(dict(r)) for r in rows),
                    key=lambda r: r["id"],
                )
        body = json.dumps(tables, sort_keys=True, separators=(",", ":"))
        return Response(content=body, media_type="application/json")

    return app


app = create_app()


def seed() -> dict:
    """Insert one demo lead; returns its id. Used by benchmarks."""
    crm_db.migrate_up()
    with _conn() as conn:
        lead_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO crm.leads (id, name, email) VALUES (%s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (lead_id, "Demo Lead", "demo@example.com"),
        )
    return {"lead_id": lead_id}


if __name__ == "__main__":
    import uvicorn

    crm_db.migrate_up()
    uvicorn.run(app, host="127.0.0.1", port=8001)
