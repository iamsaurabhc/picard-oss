from app.services.agent_memory import memory_hit_useful


def test_memory_hit_rejects_noise_tokens():
    assert not memory_hit_useful("results")
    assert not memory_hit_useful("preferences")


def test_memory_hit_accepts_actionable_preference():
    text = "Prefer tabular output with party names in the first column when listing matters."
    assert memory_hit_useful(text)
