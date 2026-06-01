from app.services.entity_extraction.recognizers.rules import ORG_PARTY_PATTERN, extract_rule_mentions


def test_org_party_pattern_matches_llc():
    text = "Defendants: Google LLC, Google India Private Limited."
    matches = [m.group(0) for m in ORG_PARTY_PATTERN.finditer(text)]
    assert "Google LLC" in matches
    assert any("Google India" in m for m in matches)


def test_extract_rule_mentions_org_party():
    text = "Proceedings against Google LLC under the Competition Act."
    mentions = extract_rule_mentions(text, early_doc=True)
    party_canonicals = [m.canonical_value for m in mentions if m.entity_type == "party"]
    assert "google llc" in party_canonicals
