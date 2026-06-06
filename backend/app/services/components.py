"""Optional component packs: OCR, GLiNER model."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.agent_pack import agent_pack_available, reset_agent_pack_probe
from app.services.entity_extraction.ner.gliner_engine import ner_available
from app.services.parse_plan import check_paddleocr_server


def _gliner_model_path() -> Path:
    return settings.picard_data_dir / "models" / settings.ner_model_name


def _ml_installed() -> bool:
    try:
        import torch  # noqa: F401
        import gliner  # noqa: F401
        return True
    except ImportError:
        return False


def list_components() -> list[dict[str, Any]]:
    ocr_url = settings.liteparse_ocr_server_url
    ocr_reachable = bool(ocr_url and check_paddleocr_server(ocr_url))
    gliner_path = _gliner_model_path()
    return [
        {
            "id": "agent",
            "name": "Agent pack (LightAgent + mem0)",
            "description": "Conversational workflow authoring and agent mode (Phase 7a).",
            "installed": agent_pack_available(),
            "running": agent_pack_available(),
            "optional": True,
            "install_hint": "pip install -r requirements-agent.txt",
        },
        {
            "id": "ocr",
            "name": "PaddleOCR upgrade (optional)",
            "description": "Higher-quality OCR for scans. Picard ships with bundled Tesseract by default.",
            "installed": ocr_reachable,
            "running": ocr_reachable,
            "optional": True,
            "install_hint": "Set LITEPARSE_OCR_SERVER_URL in Settings, then: docker compose --profile ocr up -d paddleocr",
        },
        {
            "id": "gliner",
            "name": "GLiNER entity model",
            "description": "Local NER for entity index. Skipping uses SLM + regex extraction.",
            "installed": gliner_path.is_dir() and any(gliner_path.iterdir()),
            "running": ner_available(),
            "ml_deps_installed": _ml_installed(),
            "optional": True,
            "model_path": str(gliner_path),
        },
    ]


def install_component(component_id: str) -> dict[str, Any]:
    if component_id == "agent":
        req = Path(__file__).resolve().parents[2] / "requirements-agent.txt"
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req)],
            capture_output=True,
            text=True,
            timeout=900,
            cwd=str(req.parent),
        )
        reset_agent_pack_probe()
        if proc.returncode != 0:
            return {
                "ok": False,
                "message": proc.stderr or proc.stdout or "pip install failed",
            }
        if not agent_pack_available():
            return {
                "ok": False,
                "message": (
                    "pip finished but imports still failed in this API process. "
                    "Refresh Settings or restart the backend."
                ),
            }
        return {"ok": True, "message": "Agent pack installed"}
    if component_id == "gliner":
        if not _ml_installed():
            return {
                "ok": False,
                "message": "Install ML deps first: pip install -r requirements-ml.txt",
            }
        script = Path(__file__).resolve().parents[2] / "scripts" / "download_gliner_model.py"
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(script.parents[1]),
        )
        if proc.returncode != 0:
            return {"ok": False, "message": proc.stderr or proc.stdout or "download failed"}
        return {"ok": True, "message": "GLiNER model downloaded"}
    if component_id == "ocr":
        return {
            "ok": True,
            "message": "Start PaddleOCR: docker compose --profile ocr up -d paddleocr",
        }
    return {"ok": False, "message": f"Unknown component: {component_id}"}
