"""Optional LightAgent + mem0 pack — lazy import so core desktop starts without it."""

from __future__ import annotations

import sys
from typing import Any

_IMPORT_ERROR: str | None = None


def reset_agent_pack_probe() -> None:
    """Clear last probe error so the next check re-imports (e.g. after pip install without restart)."""
    global _IMPORT_ERROR
    _IMPORT_ERROR = None


def _probe_import(module: str) -> str | None:
    """Return None if import works, else a short error string."""
    # Drop a failed partial import so a later pip install can succeed without restarting the API.
    sys.modules.pop(module, None)
    try:
        __import__(module)
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def agent_pack_available() -> bool:
    """Probe LightAgent + mem0 in the running interpreter (no long-lived cache)."""
    global _IMPORT_ERROR
    missing: list[str] = []
    la_err = _probe_import("LightAgent")
    if la_err:
        missing.append(f"lightagent ({la_err})" if "No module" not in la_err else "lightagent")
    m0_err = _probe_import("mem0")
    if m0_err:
        missing.append(f"mem0ai ({m0_err})" if "No module" not in m0_err else "mem0ai")
    if missing:
        py = sys.executable
        _IMPORT_ERROR = (
            f"Agent pack not available in this Python ({py}). "
            f"Missing: {', '.join(missing)}. "
            f"Install: cd backend && {py} -m pip install -r requirements-agent.txt "
            "Then refresh Settings (no API restart required). "
            "Desktop .app builds ship without the agent pack unless rebuilt."
        )
        return False
    _IMPORT_ERROR = None
    return True


def agent_pack_error() -> str | None:
    agent_pack_available()
    return _IMPORT_ERROR


def import_light_agent() -> Any:
    if not agent_pack_available():
        raise RuntimeError(agent_pack_error() or "Agent pack not available")
    from LightAgent import LightAgent

    return LightAgent
