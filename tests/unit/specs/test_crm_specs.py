"""H-014: all hand-written CRM specs validate; ops match the real app routes."""

from pathlib import Path

from targets.crm.app import create_app

from hyperion.specs import loader

SPECS_DIR = Path(__file__).resolve().parents[3] / "specs" / "crm"

EXPECTED_IDS = {
    "crm.leads.create", "crm.leads.read", "crm.leads.update", "crm.leads.delete",
    "crm.deals.create", "crm.deals.read", "crm.deals.update", "crm.deals.delete",
    "crm.notes.add", "crm.notes.list",
    "crm.emails.send",
}


def _known_operations() -> set[tuple[str, str]]:
    known = set()
    for route in create_app().routes:
        methods = getattr(route, "methods", None)
        if methods:
            for m in methods:
                if m != "HEAD":
                    known.add((m, route.path))
    return known


def test_all_crm_specs_validate_against_real_routes():
    known = _known_operations()
    specs = loader.load_dir(SPECS_DIR, known)
    assert set(specs) == EXPECTED_IDS


def test_emails_send_is_irreversible():
    specs = loader.load_dir(SPECS_DIR)
    email = specs["crm.emails.send"]
    assert email["effect_class"] == "irreversible"
    assert email["fidelity"] == "none"
    assert email["inverse"] is None


def test_inverse_presence_matches_class():
    specs = loader.load_dir(SPECS_DIR)
    for spec_id, spec in specs.items():
        if spec["effect_class"] in ("read", "irreversible"):
            assert spec["inverse"] is None, spec_id
        else:
            assert spec["inverse"] is not None, spec_id
