import logging
import sys
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import reload_settings, settings as app_settings
from app.db.session import init_db
from app.routers import (
    chat,
    documents,
    prompts,
    search,
    settings as settings_router,
    tabular,
    updates,
    workflows,
    workspaces,
)
from app.services.model_router import llm_available
from app.services.settings_store import ensure_user_settings_file
from app.version import build_metadata, read_version
from app.schemas import OcrHealthOut
from app.services.ingestion import recover_stuck_parsing_documents
from app.services.parse_plan import check_paddleocr_server
from app.services.tesseract_data import ensure_tesseract_data, tesseract_ready
from app.services.storage import ensure_data_dirs

logger = logging.getLogger(__name__)

# Packaged UI (13130) and dev (3000) both use loopback HTTP; regex covers stale cors_origins in settings.json.
LOCALHOST_CORS_ORIGIN_REGEX = r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$"


def _warm_embedding_model() -> None:
    from app.services.chunk_embeddings import ensure_embedding_model

    ensure_embedding_model()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_user_settings_file(app_settings.picard_data_dir)
    reload_settings()
    ensure_data_dirs()
    # Desktop PyInstaller entry configures tessdata in run_desktop.py before uvicorn starts.
    if not getattr(sys, "frozen", False):
        try:
            ensure_tesseract_data(app_settings.picard_data_dir)
        except Exception:
            logger.warning("Tesseract tessdata setup failed", exc_info=True)
    init_db()
    threading.Thread(
        target=recover_stuck_parsing_documents,
        daemon=True,
        name="recover-stuck",
    ).start()
    if app_settings.enable_hybrid_search:
        threading.Thread(target=_warm_embedding_model, daemon=True, name="embed-warmup").start()
    yield


app = FastAPI(title="Picard-OSS", version=read_version(), lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origins,
    allow_origin_regex=LOCALHOST_CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspaces.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(chat.router)
app.include_router(tabular.router)
app.include_router(settings_router.router)
app.include_router(prompts.router)
app.include_router(updates.router)
app.include_router(workflows.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version():
    return build_metadata()


@app.get("/health/llm")
def health_llm():
    return {
        "configured": llm_available(),
        "provider": app_settings.llm_provider,
        "model": app_settings.llm_model,
    }


@app.get("/health/ocr", response_model=OcrHealthOut)
def health_ocr():
    tess_ok = tesseract_ready(app_settings.picard_data_dir)
    url = app_settings.liteparse_ocr_server_url
    if not url:
        return OcrHealthOut(
            configured=False,
            server_url=None,
            reachable=tess_ok,
            engine="tesseract",
            tesseract_ready=tess_ok,
        )
    reachable = check_paddleocr_server(url)
    return OcrHealthOut(
        configured=True,
        server_url=url,
        reachable=reachable,
        engine="paddleocr" if reachable else "tesseract",
        tesseract_ready=tess_ok,
    )
