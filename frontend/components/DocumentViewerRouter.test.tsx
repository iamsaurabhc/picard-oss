import { describe, expect, it } from "vitest";
import { isDocxDocument } from "./DocumentViewerRouter";
import type { DocumentRecord } from "@/lib/picardApi";

const base: DocumentRecord = {
  id: "1",
  workspace_id: "w",
  file_name: "a.pdf",
  content_hash: null,
  page_count: 1,
  parse_status: "done",
  parse_error: null,
  text_source: "digital",
  ocr_engine: "none",
  file_type: "pdf",
  source_document_id: null,
  created_at: "2026-01-01",
};

describe("isDocxDocument", () => {
  it("detects docx", () => {
    expect(isDocxDocument({ ...base, file_type: "docx", file_name: "a.docx" })).toBe(true);
  });

  it("defaults to pdf", () => {
    expect(isDocxDocument({ ...base, file_type: "pdf" })).toBe(false);
  });
});
