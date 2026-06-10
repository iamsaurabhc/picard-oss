from __future__ import annotations

import json
import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services.chunk_builder import (
    BuiltChunk,
    _infer_chunk_type,
    _is_heading,
    _section_key,
)
from app.services.structured_table import (
    structured_table_from_docx_grid,
    table_to_built_chunks,
)

_LIST_RE = re.compile(r"^[\-\*•]\s+")


def _para_id(paragraph: Paragraph) -> str | None:
    return paragraph._p.get(qn("w14:paraId"))


def _heading_level(paragraph: Paragraph) -> int | None:
    style_name = (paragraph.style.name or "") if paragraph.style else ""
    if style_name == "Title":
        return 0
    if style_name.startswith("Heading"):
        suffix = style_name.removeprefix("Heading").strip()
        if suffix.isdigit():
            return int(suffix)
        return 1
    return None


def _paragraph_has_page_break(paragraph: Paragraph) -> bool:
    for run in paragraph.runs:
        for br in run._element.findall(qn("w:br")):
            if br.get(qn("w:type")) == "page":
                return True
    return False


def _table_to_grid(table: Table) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        rows.append(cells)
    return rows


def _placeholder_bbox(block_index: int, total_blocks: int) -> dict:
    total = max(total_blocks, 1)
    y0 = block_index / total
    y1 = min(1.0, (block_index + 1) / total)
    return {"x0": 0.0, "y0": y0, "x1": 1.0, "y1": y1}


def _infer_chunk_type_from_paragraph(paragraph: Paragraph) -> str:
    text = paragraph.text.strip()
    if not text:
        return "paragraph"
    level = _heading_level(paragraph)
    if level is not None:
        return "heading"
    if _is_heading(text):
        return "heading"
    if _LIST_RE.match(text):
        return "list"
    return _infer_chunk_type(text)


def _heading_depth_from_path(heading_path: str | None) -> int:
    if not heading_path:
        return 1
    return max(1, len(heading_path.split(" > ")))


def build_chunks_from_docx(docx_path: str) -> tuple[list[BuiltChunk], int, dict]:
    doc = Document(docx_path)
    blocks: list[tuple[str, Paragraph | Table, int]] = []
    page_number = 1
    table_counter = 0

    for item in doc.iter_inner_content():
        if isinstance(item, Paragraph):
            if _paragraph_has_page_break(item):
                page_number += 1
            text = item.text.strip()
            if not text:
                continue
            blocks.append(("paragraph", item, page_number))
        elif isinstance(item, Table):
            grid = _table_to_grid(item)
            if any(any(c.strip() for c in row) for row in grid):
                blocks.append(("table", item, page_number))

    total_blocks = max(len(blocks), 1)
    heading_stack: list[str] = []
    built: list[BuiltChunk] = []

    for block_index, (kind, item, block_page) in enumerate(blocks):
        if kind == "table":
            assert isinstance(item, Table)
            grid = _table_to_grid(item)
            heading_path = " > ".join(heading_stack) if heading_stack else None
            table_id = f"t{table_counter}"
            table_counter += 1
            structured = structured_table_from_docx_grid(
                table_id=table_id,
                rows_grid=grid,
                page_number=block_page,
                heading_path=heading_path,
                block_index=block_index,
            )
            built.extend(
                table_to_built_chunks(
                    structured,
                    page_number=block_page,
                    total_blocks=total_blocks,
                )
            )
        else:
            assert isinstance(item, Paragraph)
            text = item.text.strip()
            chunk_type = _infer_chunk_type_from_paragraph(item)
            anchor = {"para_id": _para_id(item), "block_index": block_index, "kind": chunk_type}
            if chunk_type == "heading":
                depth = _heading_level(item)
                if depth is None:
                    depth = _heading_depth_from_path(None)
                elif depth == 0:
                    heading_stack = [text]
                else:
                    heading_stack = heading_stack[: depth - 1] + [text]
                heading_path = " > ".join(heading_stack)
            else:
                heading_path = " > ".join(heading_stack) if heading_stack else None

            built.append(
                BuiltChunk(
                    page_number=block_page,
                    chunk_type=chunk_type,
                    bbox_json=json.dumps(_placeholder_bbox(block_index, total_blocks)),
                    text_content=text,
                    heading_path=heading_path,
                    section_key=_section_key(heading_path),
                    token_count=len(text.split()),
                    anchor_json=json.dumps(anchor),
                )
            )

    page_count = max((c.page_number for c in built), default=1)
    meta = {
        "text_source": "docx",
        "ocr_engine": "none",
        "page_count": page_count,
        "chunk_count": len(built),
        "table_count": table_counter,
    }
    return built, page_count, meta


def validate_docx_path(path: str | Path) -> None:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"DOCX not found: {path}")
    if p.suffix.lower() != ".docx":
        raise ValueError("Expected .docx file")
