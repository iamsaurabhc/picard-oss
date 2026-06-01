from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.session import init_db
from app.routers import chat, documents, search, workspaces
from app.schemas import OcrHealthOut
from app.services.ingestion import recover_stuck_parsing_documents
from app.services.parse_plan import check_paddleocr_server
from app.services.storage import ensure_data_dirs


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_data_dirs()
    init_db()
    recover_stuck_parsing_documents()
    yield


app = FastAPI(title="Picard-OSS", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspaces.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(chat.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/ocr", response_model=OcrHealthOut)
def health_ocr():
    url = settings.liteparse_ocr_server_url
    if not url:
        return OcrHealthOut(configured=False, server_url=None, reachable=False, engine="tesseract")
    reachable = check_paddleocr_server(url)
    return OcrHealthOut(
        configured=True,
        server_url=url,
        reachable=reachable,
        engine="paddleocr" if reachable else "tesseract",
    )
