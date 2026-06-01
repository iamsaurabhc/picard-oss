import json
from unittest.mock import MagicMock, patch

from app.config import settings
from app.services.query_planner_validation import probe_search_pass, validate_search_passes
from app.services.query_understanding import SearchPass


def test_probe_search_pass_returns_count():
    db = MagicMock()
    with patch("app.services.query_planner_validation.fts_search", return_value=[object()]):
        count = probe_search_pass(
            db,
            SearchPass(label="t", fts_terms=["a", "b"]),
            workspace_id="ws",
            document_ids=["doc"],
        )
    assert count == 1


def test_validate_repairs_zero_hit_pass():
    settings.query_planner_repair_on_zero_hits = True
    db = MagicMock()
    passes = [SearchPass(label="name", fts_terms=["badterm", "otherbad"], pin_best=True)]

    def fake_probe(db, sp, *, workspace_id, document_ids):
        return 0 if sp.fts_terms == ["badterm", "otherbad"] else 1

    repair_payload = json.dumps({
        "repairs": [{"label": "name", "fts_terms": ["janet", "son"], "operator": "AND", "pin_best": True}],
    })

    with patch("app.services.query_planner_validation.probe_search_pass", side_effect=fake_probe):
        with patch("app.services.query_planner_validation.completion", return_value=repair_payload):
            out, log = validate_search_passes(
                db,
                passes,
                query="name?",
                workspace_id="ws",
                document_ids=["doc"],
            )
    assert out[0].fts_terms == ["janet", "son"]
    assert any("repaired" in entry for entry in log)
