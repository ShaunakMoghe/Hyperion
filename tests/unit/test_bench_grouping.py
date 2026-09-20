"""M7: study context grouping (offline: inventory + app OpenAPI only)."""

from bench.synth_study import build_context, crm_inventory, stripe_inventory


def test_notes_add_sees_note_delete_candidate():
    # Regression: same-resource-only grouping hid DELETE /notes/{id}
    # (resource "notes") from notes.add (resource "deals"), leaving the
    # model no delete signal and forcing irreversible proposals.
    ctx = build_context("crm", "POST", "/deals/{deal_id}/notes",
                        crm_inventory())
    assert any(e["method"] == "DELETE" and "/notes/" in e["path"]
               for e in ctx["candidate_inverses"])


def test_single_segment_resources_unchanged():
    # For flat resources the shared-segment pool reduces to the
    # resource's own ops (no prompt change for Stripe holdouts).
    resources, _ = stripe_inventory()
    ctx = build_context("stripe", "POST", "/v1/products", resources)
    assert {e["path"] for e in ctx["candidate_inverses"]} == {
        "/v1/products/{id}", "/v1/products/{product}/features/{id}"}
