"""Provenance edge extraction (H-050): a runtime lineage approximation.

After each call, identifier-like values from its response are indexed; when a
later call's args contain an indexed value, a `provenance` edge is stored with
evidence (response path, args path). Cite Cordon for the fuller model.

Rules:
- Only string leaves of length >= 6 are indexed (short values like names or
  codes collide constantly); numbers are never indexed.
- Values at paths declared in the spec's `produces` are indexed regardless
  (declared identifiers win over heuristics).
- Raw values are NOT stored in edge evidence (they can be PII); only paths.

Limitation (documented, with an xfail test): dependencies that pass through
paraphrase or transformation are missed — matching is exact.
"""

from __future__ import annotations

import json

import psycopg
import psycopg.rows

from hyperion.ledger import store

MIN_LEN = 6


def _lookup(obj: dict, dotted: str):
    """Dotted lookup; raises KeyError when absent.

    Local copy (not executor.lookup) to avoid an import cycle:
    executor imports this module for auto-linking.
    """
    cur: object = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"missing path {dotted!r}")
        cur = cur[part]
    return cur


def _leaves(obj, prefix: str = "") -> list[tuple[str, object]]:
    """(json_path, value) for every scalar leaf."""
    out: list[tuple[str, object]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_leaves(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_leaves(v, f"{prefix}[{i}]"))
    else:
        out.append((prefix, obj))
    return out


def _produced_values(spec: dict, response: dict | None) -> dict[str, str]:
    """{value: json_path} for spec-declared produced ids (any type/length)."""
    out: dict[str, str] = {}
    if not isinstance(response, dict):
        return out
    for p in spec.get("produces") or []:
        # Malformed entries must not crash linking after a recorded call.
        frm = p.get("from") if isinstance(p, dict) else None
        if not isinstance(frm, str) or not frm.startswith("$."):
            continue
        try:
            value = _lookup({"response": response}, frm[2:])
        except KeyError:
            continue
        if value is None or isinstance(value, (dict, list)):
            continue
        out[str(value)] = frm
    return out


def indexable(response: dict | None, spec: dict | None = None) -> dict[str, str]:
    """{value: json_path} worth indexing from a call response."""
    out: dict[str, str] = {}
    if isinstance(response, dict):
        for path, value in _leaves(response):
            if isinstance(value, str) and len(value) >= MIN_LEN:
                out.setdefault(value, f"$.response.{path}")
    if spec is not None:
        for value, path in _produced_values(spec, response).items():
            out.setdefault(value, path)
    return out


def arg_refs(args: dict) -> list[tuple[str, str]]:
    """(json_path, value) string leaves of call args worth matching."""
    return [(f"$.args.{path}", value) for path, value in _leaves(args)
            if isinstance(value, str) and len(value) >= MIN_LEN]


def build_index(conn: psycopg.Connection, run_id: str,
                specs: dict[str, dict]) -> dict[str, tuple[str, str]]:
    """{value: (producing_call_id, response_path)} for executed calls."""
    conn.row_factory = psycopg.rows.dict_row
    try:
        rows = conn.execute(
            "SELECT id, system, operation, response FROM calls "
            "WHERE run_id = %s AND status = 'executed' ORDER BY seq",
            (run_id,),
        ).fetchall()
    finally:
        conn.row_factory = psycopg.rows.tuple_row
    index: dict[str, tuple[str, str]] = {}
    for row in rows:
        spec = specs.get(f"{row['system']}.{row['operation']}")
        for value, path in indexable(row["response"], spec).items():
            index.setdefault(value, (str(row["id"]), path))
    return index


def link_call(conn: psycopg.Connection, run_id: str, call_id: str,
              specs: dict[str, dict]) -> list[dict]:
    """Add provenance edges from earlier calls' responses to this call's
    args. Returns the added edges. Never matches a call to itself."""
    call = store.get_call(conn, call_id)
    args = call["args"] or {}
    index = build_index(conn, run_id, specs)
    added = []
    for args_path, value in arg_refs(args):
        hit = index.get(value)
        if hit is None or hit[0] == call_id:
            continue
        from_call, response_path = hit
        evidence = {"response_path": response_path, "args_path": args_path}
        if _insert_edge(conn, call_id, from_call, evidence):
            added.append({"from": from_call, "evidence": evidence})
    return added


def _insert_edge(conn, call_id: str, from_call: str, evidence: dict) -> bool:
    """Insert a provenance edge; False when it already existed."""
    row = conn.execute(
        """INSERT INTO edges (call_id, depends_on_call_id, kind, evidence)
           VALUES (%s, %s, 'provenance', %s)
           ON CONFLICT DO NOTHING RETURNING call_id""",
        (call_id, from_call, json.dumps(evidence)),
    ).fetchone()
    return row is not None
