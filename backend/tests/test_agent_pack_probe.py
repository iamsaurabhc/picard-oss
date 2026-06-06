from unittest.mock import patch

from app.services import agent_pack as ap


def test_agent_pack_available_reprobes_each_call():
    """Installing deps while the API runs must not stick on an old False cache."""
    calls = {"n": 0}

    def fake_probe(module: str):
        calls["n"] += 1
        if module == "LightAgent":
            return None if calls["n"] >= 3 else "ModuleNotFoundError: no"
        return None

    with patch.object(ap, "_probe_import", side_effect=fake_probe):
        ap.reset_agent_pack_probe()
        assert ap.agent_pack_available() is False
        assert ap.agent_pack_available() is True
