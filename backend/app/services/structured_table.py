"""Geometry-only table IR — row/column structure without semantic rules."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from app.services.chunk_builder import BuiltChunk, _section_key

MIN_ROW_SPLIT_CONFIDENCE = 0.5
_MAX_CELL_CHARS = 8000


@dataclass
class StructuredTable:
    table_id: str
    source: Literal["docx", "pdf"]
    page_start: int
    page_end: int
    columns: list[str]
    header_row_count: int
    rows: list[dict[str, str]]
    parse_confidence: float
    heading_path: str | None = None
    block_index: int = 0


@dataclass
class TableChunkBundle:
    chunks: list[BuiltChunk] = field(default_factory=list)
    structured: StructuredTable | None = None


def _dedupe_row_cells(cells: list[str]) -> list[str]:
    """Collapse horizontally merged cells (python-docx repeats text)."""
    if not cells:
        return cells
    out: list[str] = []
    prev = object()
    for cell in cells:
        text = cell.strip()
        if text == prev:
            continue
        out.append(text)
        prev = text
    return out


def _normalize_columns(raw: list[str]) -> list[str]:
    cols: list[str] = []
    for i, c in enumerate(raw):
        label = c.strip() or f"Column {i + 1}"
        cols.append(label)
    return cols


def structured_table_from_docx_grid(
    *,
    table_id: str,
    rows_grid: list[list[str]],
    page_number: int,
    heading_path: str | None,
    block_index: int,
    header_row_count: int = 1,
) -> StructuredTable:
    if not rows_grid:
        return StructuredTable(
            table_id=table_id,
            source="docx",
            page_start=page_number,
            page_end=page_number,
            columns=[],
            header_row_count=0,
            rows=[],
            parse_confidence=0.0,
            heading_path=heading_path,
            block_index=block_index,
        )

    header_rows = rows_grid[:header_row_count]
    data_rows = rows_grid[header_row_count:]
    columns = _normalize_columns(_dedupe_row_cells(header_rows[0]) if header_rows else [])

    if not columns:
        columns = [f"Column {i + 1}" for i in range(max(len(r) for r in rows_grid))]

    parsed_rows: list[dict[str, str]] = []
    for row_cells in data_rows:
        cells = _dedupe_row_cells(row_cells)
        if not any(c.strip() for c in cells):
            continue
        row_dict: dict[str, str] = {}
        for i, col in enumerate(columns):
            val = cells[i].strip() if i < len(cells) else ""
            if val:
                row_dict[col] = val[:_MAX_CELL_CHARS]
        if row_dict:
            parsed_rows.append(row_dict)

    confidence = 1.0 if columns and parsed_rows else 0.3
    if len(columns) >= 2 and parsed_rows:
        confidence = min(1.0, 0.7 + 0.1 * min(len(columns), 3))

    return StructuredTable(
        table_id=table_id,
        source="docx",
        page_start=page_number,
        page_end=page_number,
        columns=columns,
        header_row_count=header_row_count,
        rows=parsed_rows,
        parse_confidence=confidence,
        heading_path=heading_path,
        block_index=block_index,
    )


def format_labeled_row(
    row: dict[str, str],
    *,
    heading_path: str | None,
    columns: list[str] | None = None,
) -> str:
    lines: list[str] = []
    if heading_path:
        lines.append(f"[{heading_path}]")
    keys = columns or list(row.keys())
    for key in keys:
        val = row.get(key, "").strip()
        if val:
            lines.append(f"{key}: {val}")
    return "\n".join(lines).strip()


def format_table_header_text(table: StructuredTable) -> str:
    parts = [f"Table columns: {' | '.join(table.columns)}"]
    if table.heading_path:
        parts.insert(0, f"[{table.heading_path}]")
    return "\n".join(parts)


def format_table_index_text(table: StructuredTable) -> str | None:
    """Compact clause/topic index from first column or shortest label column."""
    if not table.rows or not table.columns:
        return None
    label_col = table.columns[1] if len(table.columns) > 1 else table.columns[0]
    labels: list[str] = []
    for row in table.rows:
        label = (row.get(label_col) or row.get(table.columns[0]) or "").strip()
        if label and label not in labels:
            labels.append(label[:200])
    if not labels:
        return None
    prefix = f"[{table.heading_path}] " if table.heading_path else ""
    return prefix + "Topics: " + "; ".join(labels[:40])


def _placeholder_bbox(block_index: int, total_blocks: int) -> dict:
    total = max(total_blocks, 1)
    y0 = block_index / total
    y1 = min(1.0, (block_index + 1) / total)
    return {"x0": 0.0, "y0": y0, "x1": 1.0, "y1": y1}


def _row_bbox(block_index: int, total_blocks: int, row_index: int, row_count: int) -> dict:
    base = _placeholder_bbox(block_index, total_blocks)
    if row_count <= 1:
        return base
    span = (base["y1"] - base["y0"]) / row_count
    y0 = base["y0"] + row_index * span
    return {"x0": 0.0, "y0": y0, "x1": 1.0, "y1": min(base["y1"], y0 + span)}


def table_to_built_chunks(
    table: StructuredTable,
    *,
    page_number: int,
    total_blocks: int,
    include_index: bool = True,
) -> list[BuiltChunk]:
    """Convert StructuredTable to table_header + table_row chunks (or monolithic fallback)."""
    if table.parse_confidence < MIN_ROW_SPLIT_CONFIDENCE or not table.rows:
        flat_rows = []
        if table.columns:
            flat_rows.append("\t".join(table.columns))
        for row in table.rows:
            flat_rows.append("\t".join(row.get(c, "") for c in table.columns))
        text = "\n".join(flat_rows).strip()
        if not text:
            return []
        anchor = {
            "kind": "table",
            "table_id": table.table_id,
            "block_index": table.block_index,
            "parse_confidence": table.parse_confidence,
        }
        return [
            BuiltChunk(
                page_number=page_number,
                chunk_type="table",
                bbox_json=json.dumps(_placeholder_bbox(table.block_index, total_blocks)),
                text_content=text,
                heading_path=table.heading_path,
                section_key=_section_key(table.heading_path),
                token_count=len(text.split()),
                anchor_json=json.dumps(anchor),
            )
        ]

    built: list[BuiltChunk] = []
    header_text = format_table_header_text(table)
    built.append(
        BuiltChunk(
            page_number=page_number,
            chunk_type="table_header",
            bbox_json=json.dumps(_placeholder_bbox(table.block_index, total_blocks)),
            text_content=header_text,
            heading_path=table.heading_path,
            section_key=_section_key(table.heading_path),
            token_count=len(header_text.split()),
            anchor_json=json.dumps(
                {
                    "kind": "table_header",
                    "table_id": table.table_id,
                    "columns": table.columns,
                    "block_index": table.block_index,
                    "parse_confidence": table.parse_confidence,
                }
            ),
        )
    )

    if include_index:
        index_text = format_table_index_text(table)
        if index_text:
            built.append(
                BuiltChunk(
                    page_number=page_number,
                    chunk_type="table_header",
                    bbox_json=json.dumps(_placeholder_bbox(table.block_index, total_blocks)),
                    text_content=index_text,
                    heading_path=table.heading_path,
                    section_key=_section_key(table.heading_path),
                    token_count=len(index_text.split()),
                    anchor_json=json.dumps(
                        {
                            "kind": "table_index",
                            "table_id": table.table_id,
                            "block_index": table.block_index,
                        }
                    ),
                )
            )

    row_count = len(table.rows)
    label_col = table.columns[1] if len(table.columns) > 1 else (table.columns[0] if table.columns else None)
    for row_idx, row in enumerate(table.rows):
        text = format_labeled_row(row, heading_path=table.heading_path, columns=table.columns)
        if not text:
            continue
        primary_label = (row.get(label_col) or row.get(table.columns[0]) or "").strip() if table.columns else ""
        built.append(
            BuiltChunk(
                page_number=page_number,
                chunk_type="table_row",
                bbox_json=json.dumps(_row_bbox(table.block_index, total_blocks, row_idx, row_count)),
                text_content=text,
                heading_path=table.heading_path,
                section_key=_section_key(
                    f"{table.heading_path} > {primary_label}" if primary_label and table.heading_path else primary_label or table.heading_path
                ),
                token_count=len(text.split()),
                anchor_json=json.dumps(
                    {
                        "kind": "table_row",
                        "table_id": table.table_id,
                        "row_index": row_idx,
                        "columns": table.columns,
                        "primary_label": primary_label[:300] if primary_label else None,
                        "parse_confidence": table.parse_confidence,
                        "block_index": table.block_index,
                    }
                ),
            )
        )
    return built


# --- PDF geometry helpers ---

_TAB_ROW_RE = re.compile(r"\t")
_MULTI_SPACE_RE = re.compile(r"\s{3,}")


def _split_pdf_line_to_cells(text: str) -> list[str]:
    if "\t" in text:
        return [c.strip() for c in text.split("\t")]
    parts = _MULTI_SPACE_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


@dataclass
class _PdfTableLine:
    page_number: int
    y0: float
    cells: list[str]


def structured_table_from_pdf_lines(
    lines: list,
    *,
    table_id: str,
    heading_path: str | None,
    block_index: int,
    header_row_count: int = 1,
) -> StructuredTable:
    """Build StructuredTable from grouped PDF table lines (ParsedLine-like objects)."""
    if not lines:
        return StructuredTable(
            table_id=table_id,
            source="pdf",
            page_start=1,
            page_end=1,
            columns=[],
            header_row_count=0,
            rows=[],
            parse_confidence=0.0,
            heading_path=heading_path,
            block_index=block_index,
        )

    parsed_lines: list[_PdfTableLine] = []
    for line in lines:
        cells = _split_pdf_line_to_cells(line.text)
        if len(cells) < 2:
            continue
        parsed_lines.append(
            _PdfTableLine(page_number=line.page_number, y0=line.y0, cells=cells)
        )

    if not parsed_lines:
        mono = "\n".join(l.text for l in lines).strip()
        return StructuredTable(
            table_id=table_id,
            source="pdf",
            page_start=lines[0].page_number,
            page_end=lines[-1].page_number,
            columns=[],
            header_row_count=0,
            rows=[],
            parse_confidence=0.2 if mono else 0.0,
            heading_path=heading_path,
            block_index=block_index,
        )

    col_counts = [len(pl.cells) for pl in parsed_lines]
    mode_count = max(set(col_counts), key=col_counts.count)
    stable = [pl for pl in parsed_lines if len(pl.cells) == mode_count]
    confidence = len(stable) / max(len(parsed_lines), 1)
    if mode_count < 2:
        confidence *= 0.5

    if len(stable) < header_row_count + 1:
        header_row_count = 1 if stable else 0

    header_cells = stable[0].cells if stable else []
    columns = _normalize_columns(header_cells)
    data_lines = stable[header_row_count:]

    rows: list[dict[str, str]] = []
    for pl in data_lines:
        cells = pl.cells
        row_dict: dict[str, str] = {}
        for i, col in enumerate(columns):
            val = cells[i].strip() if i < len(cells) else ""
            if val:
                row_dict[col] = val[:_MAX_CELL_CHARS]
        if row_dict:
            rows.append(row_dict)

    return StructuredTable(
        table_id=table_id,
        source="pdf",
        page_start=stable[0].page_number if stable else lines[0].page_number,
        page_end=stable[-1].page_number if stable else lines[-1].page_number,
        columns=columns,
        header_row_count=header_row_count,
        rows=rows,
        parse_confidence=round(confidence, 3),
        heading_path=heading_path,
        block_index=block_index,
    )
