"""LiteParse-compatible PaddleOCR HTTP server (default port 8829)."""

from __future__ import annotations

import io
import logging
import traceback
from typing import Any

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi import File as UploadFileField
from fastapi import Form, UploadFile
from paddleocr import PaddleOCR
from PIL import Image
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class OcrResponse(BaseModel):
    results: list[Any]


class StatusResponse(BaseModel):
    status: str


class PaddleOCRServer:
    def __init__(self) -> None:
        self.ocr: PaddleOCR = PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
        )
        self.current_language: str = "en"

    @staticmethod
    def normalize_language(language: str) -> str:
        normalized = language.lower()
        aliases = {
            "eng": "en",
            "zh": "ch",
            "zh-cn": "ch",
            "zh-hans": "ch",
            "zh-tw": "chinese_cht",
            "zh-hant": "chinese_cht",
            "ja": "japan",
            "ko": "korean",
        }
        return aliases.get(normalized, normalized)

    def create_app(self) -> FastAPI:
        app = FastAPI()

        @app.post("/ocr")
        async def ocr_endpoint(
            file: UploadFile = UploadFileField(...),
            language: str = Form(default="en"),
        ) -> OcrResponse:
            language = self.normalize_language(language)
            try:
                if self.current_language != language:
                    self.ocr = PaddleOCR(
                        lang=language,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=True,
                    )
                    self.current_language = language

                image_data = await file.read()
                image = Image.open(io.BytesIO(image_data))
                if image.mode != "RGB":
                    image = image.convert("RGB")
                image_array = np.array(image)
                results = self.ocr.predict(image_array)
            except ValueError as ve:
                if "No models are available for the language" in str(ve):
                    raise HTTPException(status_code=400, detail=str(ve)) from ve
                raise HTTPException(status_code=500, detail=str(ve)) from ve
            except Exception as e:
                logger.error("OCR failed:\n%s", traceback.format_exc())
                raise HTTPException(status_code=500, detail=str(e)) from e

            formatted: list[dict[str, Any]] = []
            if results and len(results) > 0:
                result = results[0]
                res_data = result.get("res", result) if isinstance(result, dict) else result
                if isinstance(res_data, dict):
                    texts = res_data.get("rec_texts", [])
                    scores = res_data.get("rec_scores", [])
                    boxes = res_data.get("rec_boxes", [])
                else:
                    texts = getattr(res_data, "rec_texts", []) or []
                    scores = getattr(res_data, "rec_scores", []) or []
                    boxes = getattr(res_data, "rec_boxes", []) or []

                if hasattr(texts, "tolist"):
                    texts = texts.tolist()
                if hasattr(scores, "tolist"):
                    scores = scores.tolist()
                if hasattr(boxes, "tolist"):
                    boxes = boxes.tolist()

                for i in range(len(texts)):
                    text = texts[i]
                    confidence = float(scores[i]) if i < len(scores) else 0.0
                    if i < len(boxes):
                        box = boxes[i]
                        bbox = box.tolist() if hasattr(box, "tolist") else list(box)
                    else:
                        bbox = [0, 0, 0, 0]
                    formatted.append({"text": text, "bbox": bbox, "confidence": confidence})

            return OcrResponse(results=formatted)

        @app.get("/health")
        def health() -> StatusResponse:
            return StatusResponse(status="healthy")

        return app

    def serve(self, host: str = "0.0.0.0", port: int = 8829) -> None:
        uvicorn.run(self.create_app(), host=host, port=port)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting PaddleOCR server on port 8829")
    PaddleOCRServer().serve()
