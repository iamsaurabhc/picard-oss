from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass

HEADING_PATTERN = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s+)?(?:Section|Article|Condition|Clause|Part)\s+[A-Z0-9]+",
    re.IGNORECASE,
)
CONDITION_PATTERN = re.compile(r"\bCondition\s+([A-Z0-9]+)\b", re.IGNORECASE)
NUMBERED_HEADING = re.compile(r"^\d+(?:\.\d+)+\.?\s+\S")


@dataclass
class ParsedLine:
    page_number: int
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page_width: float
    page_height: float


@dataclass
class BuiltChunk:
    page_number: int
    chunk_type: str
    bbox_json: str
    text_content: str
    heading_path: str | None
    section_key: str | None
    token_count: int
    anchor_json: str | None = None


def _section_key(heading_path: str | None) -> str | None:
    if not heading_path:
        return None
    return hashlib.sha256(heading_path.encode("utf-8")).hexdigest()[:16]


def _normalize_bbox(x0: float, y0: float, x1: float, y1: float, pw: float, ph: float) -> dict:
    pw = pw or 1.0
    ph = ph or 1.0
    return {
        "x0": max(0.0, min(1.0, x0 / pw)),
        "y0": max(0.0, min(1.0, y0 / ph)),
        "x1": max(0.0, min(1.0, x1 / pw)),
        "y1": max(0.0, min(1.0, y1 / ph)),
    }


def _is_heading(text: str) -> bool:
    t = text.strip()
    if len(t) < 3:
        return False
    if HEADING_PATTERN.match(t) or CONDITION_PATTERN.search(t):
        return True
    if NUMBERED_HEADING.match(t) and len(t) < 120:
        return True
    if t.isupper() and len(t.split()) <= 12:
        return True
    return False


def _infer_chunk_type(text: str) -> str:
    if _is_heading(text):
        return "heading"
    if "\t" in text or re.search(r"\s{3,}\S+\s{3,}", text):
        return "table"
    if re.match(r"^[\-\*•]\s+", text.strip()):
        return "list"
    return "paragraph"


def _extract_lines_from_liteparse(result) -> list[ParsedLine]:
    lines: list[ParsedLine] = []
    pages = getattr(result, "pages", None) or []
    for page_idx, page in enumerate(pages, start=1):
        page_number = (
            getattr(page, "page_num", None)
            or getattr(page, "page_number", None)
            or getattr(page, "number", None)
            or page_idx
        )
        page_width = float(getattr(page, "width", 612) or 612)
        page_height = float(getattr(page, "height", 792) or 792)
        items = getattr(page, "text_items", None) or getattr(page, "items", []) or []
        for item in items:
            text = (getattr(item, "text", None) or "").strip()
            if len(text) < 2:
                continue
            x = float(getattr(item, "x", 0) or 0)
            y = float(getattr(item, "y", 0) or 0)
            w = float(getattr(item, "width", 0) or getattr(item, "w", 0) or 0)
            h = float(getattr(item, "height", 0) or getattr(item, "h", 0) or 0)
            if w <= 0 and hasattr(item, "x1"):
                w = float(getattr(item, "x1", x)) - x
            if h <= 0 and hasattr(item, "y1"):
                h = float(getattr(item, "y1", y)) - y
            lines.append(
                ParsedLine(
                    page_number=int(page_number),
                    text=text,
                    x0=x,
                    y0=y,
                    x1=x + (w if w > 2 else page_width * 0.8),
                    y1=y + (h if h > 2 else max(12.0, page_height * 0.018)),
                    page_width=page_width,
                    page_height=page_height,
                )
            )
    return lines


def _group_lines_into_chunks(lines: list[ParsedLine]) -> list[BuiltChunk]:
    if not lines:
        return []

    from app.services.structured_table import (
        structured_table_from_pdf_lines,
        table_to_built_chunks,
    )

    chunks: list[BuiltChunk] = []
    heading_stack: list[str] = []
    current_page = lines[0].page_number
    group: list[ParsedLine] = []
    group_type = "paragraph"
    table_counter = 0
    block_index = 0
    total_blocks_est = max(len(lines) // 3, 1)

    def flush_group() -> None:
        nonlocal group, group_type, block_index, table_counter
        if not group:
            return
        heading_path = " > ".join(heading_stack) if heading_stack else None
        if group_type == "table":
            table_id = f"t{table_counter}"
            table_counter += 1
            structured = structured_table_from_pdf_lines(
                group,
                table_id=table_id,
                heading_path=heading_path,
                block_index=block_index,
            )
            block_index += 1
            page_num = group[0].page_number
            chunks.extend(
                table_to_built_chunks(
                    structured,
                    page_number=page_num,
                    total_blocks=total_blocks_est,
                )
            )
            group = []
            return

        text = "\n".join(l.text for l in group)
        if len(text.strip()) < 3:
            group = []
            return
        x0 = min(l.x0 for l in group)
        y0 = min(l.y0 for l in group)
        x1 = max(l.x1 for l in group)
        y1 = max(l.y1 for l in group)
        pw = group[0].page_width
        ph = group[0].page_height
        chunks.append(
            BuiltChunk(
                page_number=group[0].page_number,
                chunk_type=group_type,
                bbox_json=json.dumps(_normalize_bbox(x0, y0, x1, y1, pw, ph)),
                text_content=text,
                heading_path=heading_path,
                section_key=_section_key(heading_path),
                token_count=len(text.split()),
            )
        )
        block_index += 1
        group = []

    for line in lines:
        if line.page_number != current_page and group_type != "table":
            flush_group()
            current_page = line.page_number
        elif line.page_number != current_page and group_type == "table":
            current_page = line.page_number

        ctype = _infer_chunk_type(line.text)
        if ctype == "heading":
            flush_group()
            title = line.text.strip()
            if heading_stack and len(title) < len(heading_stack[-1]):
                heading_stack = heading_stack[:-1]
            heading_stack.append(title)
            heading_path = " > ".join(heading_stack)
            chunks.append(
                BuiltChunk(
                    page_number=line.page_number,
                    chunk_type="heading",
                    bbox_json=json.dumps(
                        _normalize_bbox(line.x0, line.y0, line.x1, line.y1, line.page_width, line.page_height)
                    ),
                    text_content=title,
                    heading_path=heading_path,
                    section_key=_section_key(heading_path),
                    token_count=len(title.split()),
                )
            )
            block_index += 1
            continue

        if not group:
            group = [line]
            group_type = ctype
            continue

        prev = group[-1]
        vertical_gap = line.y0 - prev.y1
        same_block = vertical_gap < max(18.0, prev.page_height * 0.025)
        if same_block and ctype == group_type:
            group.append(line)
        else:
            flush_group()
            group = [line]
            group_type = ctype

    flush_group()
    return chunks


def build_chunks_from_pdf(pdf_path: str, plan: ParsePlan | None = None) -> tuple[list[BuiltChunk], int, dict]:
    from liteparse import LiteParse

    from app.services.parse_plan import ParsePlan, build_parse_plan

    if plan is None:
        plan = build_parse_plan(pdf_path)
    parser = LiteParse(
        ocr_enabled=plan.ocr_enabled,
        ocr_server_url=plan.ocr_server_url,
        ocr_language=plan.ocr_language,
        dpi=plan.dpi,
        quiet=True,
    )
    result = parser.parse(pdf_path)
    lines = _extract_lines_from_liteparse(result)
    chunks = _group_lines_into_chunks(lines)
    if hasattr(result, "pages") and result.pages:
        page_count = len(result.pages)
    else:
        page_count = max((c.page_number for c in chunks), default=0)
    meta = _parse_meta_from_plan(plan, page_count=page_count, chunk_count=len(chunks))
    return chunks, page_count, meta


def _parse_meta_from_plan(plan: ParsePlan, *, page_count: int, chunk_count: int) -> dict:
    return {
        **plan.to_dict(),
        "page_count": page_count,
        "chunk_count": chunk_count,
    }


def new_chunk_id() -> str:
    return str(uuid.uuid4())
