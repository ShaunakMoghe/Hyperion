"""H-050: provenance indexing guards (pure: no DB)."""

import pytest

from hyperion.executor import provenance

UUID = "12345678-1234-1234-1234-123456789012"


def test_long_string_leaves_indexed():
    idx = provenance.indexable({"id": UUID, "name": "Jonathan"})
    assert idx[UUID] == "$.response.id"
    assert idx["Jonathan"] == "$.response.name"


def test_short_strings_and_numbers_excluded():
    idx = provenance.indexable({"code": "abc", "n": 500000,
                                "stage": "open", "flag": True})
    assert idx == {}


def test_declared_produces_indexed_despite_length():
    spec = {"produces": [{"name": "code", "from": "$.response.code"}]}
    assert provenance.indexable({"code": "ab"}, spec) == {"ab": "$.response.code"}


def test_arg_refs_skip_short_values():
    refs = provenance.arg_refs({"lead_id": UUID, "note": "hi", "n": 7})
    assert refs == [("$.args.lead_id", UUID)]


@pytest.mark.xfail(reason="paraphrased/transformed values are missed "
                          "(documented approximation limit)")
def test_transformed_value_links():
    # A downstream arg carrying only a case-folded copy of an id.
    assert UUID.lower().replace("-", "") in provenance.indexable({"id": UUID})


def test_malformed_produces_entries_skipped_not_raised():
    spec = {"produces": [
        {"name": "missing-from"},
        "not-a-dict",
        {"name": "relative", "from": "response.id"},
        {"name": "none-id", "from": "$.response.nothing"},
        {"name": "null-id", "from": "$.response.nil"},
        {"name": "dict-id", "from": "$.response.obj"},
        {"name": "good", "from": "$.response.id"},
    ]}
    response = {"id": UUID, "nil": None, "obj": {"nested": True}}
    # "nothing" is absent (KeyError path), nil/obj are non-scalars.
    assert provenance.indexable(response, spec) == {UUID: "$.response.id"}
    assert provenance._produced_values(spec, response) == {
        UUID: "$.response.id"}


def test_produces_none_treated_as_empty():
    assert provenance._produced_values({"produces": None},
                                       {"id": UUID}) == {}
