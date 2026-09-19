"""H-011: each validator rule has a good case and a failing case."""

import copy

from hyperion.specs import loader

GOOD = {
    "spec_version": 1,
    "id": "crm.leads.update",
    "system": "crm",
    "operation": {"method": "PATCH", "path": "/leads/{id}"},
    "effect_class": "reversible",
    "fidelity": "exact",
    "before_image": {
        "read": {"method": "GET", "path": "/leads/{id}",
                 "params": {"id": "$.args.id"}},
        "fields": ["name", "email"],
    },
    "produces": [],
    "inverse": {
        "operation": {"method": "PATCH", "path": "/leads/{id}"},
        "params": {"id": "$.args.id"},
        "body_from_before_image": ["name", "email"],
    },
    "verify": {
        "read": {"method": "GET", "path": "/leads/{id}",
                 "params": {"id": "$.args.id"}},
        "compare": {"fields": ["name", "email"], "against": "before_image"},
    },
    "provenance": {"source": "human", "model": None, "verified": False,
                   "trials": 0, "reviewed_by": None},
}

KNOWN = {("PATCH", "/leads/{id}"), ("GET", "/leads/{id}")}


def test_good_spec_passes():
    assert loader.validate(GOOD, KNOWN) == []


def test_bad_template_root():
    bad = copy.deepcopy(GOOD)
    bad["inverse"]["params"] = {"id": "$.session.id"}
    assert any("root" in e for e in loader.validate(bad))


def test_irreversible_requires_fidelity_none():
    bad = copy.deepcopy(GOOD)
    bad["effect_class"] = "irreversible"
    bad["fidelity"] = "exact"
    bad["inverse"] = None
    assert any("fidelity" in e for e in loader.validate(bad))


def test_irreversible_requires_null_inverse():
    bad = copy.deepcopy(GOOD)
    bad["effect_class"] = "irreversible"
    bad["fidelity"] = "none"
    assert any("inverse" in e for e in loader.validate(bad))


def test_reversible_requires_inverse():
    bad = copy.deepcopy(GOOD)
    bad["inverse"] = None
    assert any("inverse" in e for e in loader.validate(bad))


def test_reversible_requires_before_image_fields():
    bad = copy.deepcopy(GOOD)
    bad["before_image"]["fields"] = []
    assert any("before_image.fields" in e for e in loader.validate(bad))


def test_create_style_may_omit_before_image():
    create = copy.deepcopy(GOOD)
    create["operation"] = {"method": "POST", "path": "/leads"}
    create["before_image"] = None
    create["produces"] = [{"name": "lead_id", "from": "$.response.id"}]
    create["inverse"] = {
        "operation": {"method": "DELETE", "path": "/leads/{lead_id}"},
        "params": {"lead_id": "$.produced.lead_id"},
        "body_from_before_image": [],
    }
    create["fidelity"] = "equivalent"
    known = {("POST", "/leads"), ("DELETE", "/leads/{lead_id}"),
             ("GET", "/leads/{id}")}
    assert loader.validate(create, known) == []


def test_produces_must_read_response():
    bad = copy.deepcopy(GOOD)
    bad["operation"] = {"method": "POST", "path": "/leads"}
    bad["produces"] = [{"name": "lead_id", "from": "$.args.id"}]
    bad["inverse"] = {
        "operation": {"method": "DELETE", "path": "/leads/{id}"},
        "params": {"id": "$.produced.lead_id"},
        "body_from_before_image": [],
    }
    errs = loader.validate(bad)
    assert any("produces" in e for e in errs)


def test_compensable_requires_compensated():
    bad = copy.deepcopy(GOOD)
    bad["effect_class"] = "compensable"
    bad["fidelity"] = "exact"
    assert any("fidelity" in e for e in loader.validate(bad))


def test_unknown_operation_rejected_when_known_supplied():
    bad = copy.deepcopy(GOOD)
    bad["operation"] = {"method": "DELETE", "path": "/everything"}
    assert any("unknown operation" in e for e in loader.validate(bad, KNOWN))


def test_schema_violation_short_circuits():
    bad = copy.deepcopy(GOOD)
    del bad["id"]
    assert any(e.startswith("schema:") for e in loader.validate(bad))
