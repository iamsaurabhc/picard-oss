import json

from app.services.query_understanding import (
    QueryUnderstanding,
    _apply_overview_fields,
    _case_name_terms,
    _party_from_filed_by_phrase,
)


def test_party_from_filed_by_phrase_extracts_informant():
    q = "give in-depth case details filed by Kshitiz Arya in CCI"
    party = _party_from_filed_by_phrase(q)
    assert party is not None
    assert "kshitiz" in party.canonical
    assert "arya" in party.canonical


def test_apply_overview_fields_sets_target_entity_for_filed_by():
    u = QueryUnderstanding(intent="case_overview")
    u = _apply_overview_fields(
        u,
        "give in-depth case details filed by Kshitiz Arya in CCI",
    )
    assert u.target_entity is not None
    assert "kshitiz" in u.target_entity.canonical
    assert any(c.type == "party" for c in u.constraints)


def test_party_scoped_flag_is_json_serializable_bool():
    """Regression: `x and target_entity` must not leak TargetEntity into SSE diagnostics."""
    q = "give in-depth case details filed by Kshitiz Arya in CCI"
    u = QueryUnderstanding(intent="case_overview")
    u = _apply_overview_fields(u, q)
    party_scoped = (
        not _case_name_terms(q)
        and (
            u.target_entity is not None
            or any(c.type == "party" for c in u.constraints)
        )
    )
    assert party_scoped is True
    assert isinstance(party_scoped, bool)
    json.dumps({"party_scoped_discovery": party_scoped})
