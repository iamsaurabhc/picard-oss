from unittest.mock import patch

from app.config import settings
from app.services.query_expansion import expand_query, expansion_search_passes


def test_heuristic_expansion_liability_cap():
    settings.enable_query_expansion = True
    with patch("app.services.query_expansion.completion", return_value=None):
        result = expand_query("What is the liability cap?")
    assert result.source == "heuristic"
    assert any("limitation" in p.casefold() for p in result.phrases)


def test_expansion_search_passes_or():
    passes = expansion_search_passes(["damages claimed", "relief sought"])
    assert passes
    assert passes[0].operator == "OR"
    assert passes[0].label == "expansion_broad"
