const PAGE_CITATION_RE = /\[\[page:(\d+)\|\|(?:quote:)?((?:[^\[\]]|\[[^\]]*\])+)\]\]/gi;

export type ParsedCitation = {
  page: number;
  quote: string;
};

export function preprocessCitations(text: string): {
  processed: string;
  citations: ParsedCitation[];
} {
  const citations: ParsedCitation[] = [];
  PAGE_CITATION_RE.lastIndex = 0;
  const processed = text.replace(PAGE_CITATION_RE, (_, page, quote) => {
    const idx = citations.length;
    citations.push({ page: parseInt(page, 10), quote: String(quote).trim() });
    return `§${idx}§`;
  });
  return { processed, citations };
}

export function stripCitationsForExport(text: string | null | undefined): string {
  if (!text) return "";
  return text
    .replace(/\[\[[^\]]+\]\]/g, "")
    .replace(/\[\d+\]/g, "")
    .replace(/[ \t]+/g, " ")
    .trim();
}

const CELL_REF_RE = /\[\[cell:([^:\]]+):([^\]]+)\]\]/g;

export function parseCellRefs(text: string): { column_key: string; document_id: string }[] {
  const refs: { column_key: string; document_id: string }[] = [];
  CELL_REF_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = CELL_REF_RE.exec(text)) !== null) {
    refs.push({ column_key: m[1], document_id: m[2] });
  }
  return refs;
}
