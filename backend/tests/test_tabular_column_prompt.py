import json


def test_generate_column_prompt_with_idea(client, monkeypatch):
    payload = json.dumps(
        {
            "prompt": "State liquidated damages cap and triggers in max 2 sentences.",
            "format": "text",
        }
    )

    monkeypatch.setattr("app.services.model_router.completion", lambda **kwargs: payload)

    r = client.post(
        "/tabular/generate-column-prompt",
        json={
            "label": "Liquidated damages",
            "idea": "cap amount and triggers for LDs",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert "liquidated" in data["prompt"].casefold() or "damages" in data["prompt"].casefold()
    assert data["suggested_format"] == "text"
    assert data["from_preset"] is False


def test_generate_column_prompt_preset_label(client):
    r = client.post(
        "/tabular/generate-column-prompt",
        json={"label": "Governing Law", "format": "text"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["from_preset"] is True
    assert "governing law" in data["prompt"].casefold() or "New York" in data["prompt"]
