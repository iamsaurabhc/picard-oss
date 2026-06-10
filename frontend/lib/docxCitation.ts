import type { SuperDocInstance } from "@superdoc-dev/react";
import type { ChatReference } from "@/lib/picardApi";

/** SuperDoc highlight color — 6-digit hex with `#` prefix. */
export const CITATION_HIGHLIGHT_COLOR = "#fff59d";

export const DOCX_CITATION_HIGHLIGHT_CLASS = "picard-docx-citation-highlight";

type QueryMatchItem = {
  handle?: { ref?: string };
  target?: unknown;
  address?: { nodeId?: string };
  blocks?: Array<{ blockId?: string; ref?: string }>;
};

type QueryMatchOutput = {
  items?: QueryMatchItem[];
  matches?: Array<{ ref?: string }>;
};

type DocApi = {
  query?: {
    match?: (input: {
      select: {
        type: "text";
        pattern: string;
        mode?: "contains" | "regex";
        caseSensitive?: boolean;
      };
      require?: string;
      limit?: number;
    }) => Promise<QueryMatchOutput> | QueryMatchOutput;
  };
  format?: {
    highlight?: (input: { ref: string; value?: string | null }) => unknown;
    apply?: (input: { ref: string; inline: { highlight: string | null } }) => unknown;
  };
};

type EditorWithDoc = {
  doc?: DocApi;
};

let activeHighlightRef: string | null = null;

/** Pick a short, distinctive search string from a table-row citation excerpt. */
export function citationSearchPattern(ref: ChatReference): string | null {
  const text = (ref.pinpoint_quote || ref.preview || "").trim();
  if (!text) return null;

  const clauseMatch = text.match(/^Clause:\s*(.+)$/im);
  if (clauseMatch?.[1]?.trim()) {
    return clauseMatch[1].trim().slice(0, 120);
  }

  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

  for (const line of lines) {
    if (line.startsWith("[") && line.endsWith("]")) continue;
    if (line.startsWith("Sl No.:")) continue;
    if (line.startsWith("Table columns:")) continue;
    if (line.startsWith("Topics:")) continue;
    if (line.startsWith("Clause:")) {
      const val = line.slice("Clause:".length).trim();
      if (val.length >= 4) return val.slice(0, 120);
    }
    const colonIdx = line.indexOf(":");
    if (colonIdx > 0) {
      const val = line.slice(colonIdx + 1).trim();
      if (val.length >= 10) return val.slice(0, 120);
    }
  }

  const fallback = lines.find((l) => !l.startsWith("[")) ?? lines[0];
  return fallback ? fallback.slice(0, 80) : null;
}

function clauseFromClaim(claimText?: string): string | null {
  if (!claimText?.trim()) return null;
  const cleaned = claimText.replace(/\[\d+\]/g, "").trim();
  const colon = cleaned.indexOf(":");
  if (colon > 3) return cleaned.slice(0, colon).trim().slice(0, 120);
  return cleaned.length >= 4 ? cleaned.slice(0, 80) : null;
}

function addPattern(patterns: string[], value: string | null | undefined) {
  const trimmed = value?.trim();
  if (!trimmed || trimmed.length < 4) return;
  if (!patterns.some((p) => p.toLowerCase() === trimmed.toLowerCase())) {
    patterns.push(trimmed);
  }
}

/** Distinctive substrings likely to appear verbatim in the DOCX (not LLM paraphrases). */
function addDocumentLikePatterns(patterns: string[], value: string | null | undefined) {
  const trimmed = value?.trim();
  if (!trimmed || trimmed.length < 4) return;

  addPattern(patterns, trimmed);

  // Entity names and defined terms often contain commas — search each segment.
  for (const part of trimmed.split(/[,;]/)) {
    const segment = part.trim();
    if (segment.length >= 8) addPattern(patterns, segment);
  }

  // Longer synthesized excerpts rarely match word-for-word; try shorter anchors.
  if (trimmed.length > 48) {
    addPattern(patterns, trimmed.slice(0, 48));
  }
  if (trimmed.length > 24) {
    addPattern(patterns, trimmed.slice(0, 24));
  }
}

/** Ordered search strings — most specific first. */
export function citationSearchPatterns(ref: ChatReference, claimText?: string): string[] {
  const patterns: string[] = [];
  addDocumentLikePatterns(patterns, clauseFromClaim(claimText));
  addDocumentLikePatterns(patterns, citationSearchPattern(ref));

  const preview = (ref.preview || ref.pinpoint_quote || "").trim();
  for (const line of preview.split("\n")) {
    const trimmed = line.trim();
    if (trimmed.startsWith("Clause:")) {
      addDocumentLikePatterns(patterns, trimmed.slice("Clause:".length));
    }
    // Preferred/fallback text in chunk excerpts is often paraphrased — only short anchors.
    if (trimmed.startsWith("Preferred positions:")) {
      const val = trimmed.slice("Preferred positions:".length).trim();
      if (val.length <= 60) addDocumentLikePatterns(patterns, val);
    }
    if (trimmed.startsWith("Fallback positions:")) {
      const val = trimmed.slice("Fallback positions:".length).trim();
      if (val.length <= 60) addDocumentLikePatterns(patterns, val);
    }
    if (trimmed.startsWith("Entity Name:")) {
      addDocumentLikePatterns(patterns, trimmed.slice("Entity Name:".length));
    }
  }

  if (claimText) {
    const claim = claimText.replace(/\[\d+\]/g, "").trim();
    const colon = claim.indexOf(":");
    if (colon > 3) {
      addDocumentLikePatterns(patterns, claim.slice(0, colon).trim());
    }
  }

  return patterns;
}

async function safeQueryMatch(
  doc: DocApi,
  pattern: string
): Promise<QueryMatchItem | null> {
  if (!doc.query?.match) return null;
  try {
    const raw = await Promise.resolve(
      doc.query.match({
        select: { type: "text", pattern, mode: "contains", caseSensitive: false },
        require: "any",
        limit: 1,
      })
    );
    return firstMatchItem(raw);
  } catch {
    // require:"first" / zero-match paths can throw PlanError (MATCH_NOT_FOUND).
    return null;
  }
}

function activeDoc(instance: SuperDocInstance | null): DocApi | null {
  const editor = (instance?.activeEditor ?? null) as EditorWithDoc | null;
  return editor?.doc ?? null;
}

function firstMatchItem(result: QueryMatchOutput | null | undefined): QueryMatchItem | null {
  if (!result) return null;
  const item = result.items?.[0];
  if (item) return item;
  const legacyRef = result.matches?.[0]?.ref;
  if (legacyRef) return { handle: { ref: legacyRef } };
  return null;
}

async function clearActiveHighlight(doc: DocApi): Promise<void> {
  if (!activeHighlightRef) return;
  const ref = activeHighlightRef;
  activeHighlightRef = null;
  try {
    if (doc.format?.highlight) {
      await Promise.resolve(doc.format.highlight({ ref, value: null }));
    } else if (doc.format?.apply) {
      await Promise.resolve(doc.format.apply({ ref, inline: { highlight: null } }));
    }
  } catch {
    // Clearing a stale ref is best-effort.
  }
}

async function applyDocumentHighlight(doc: DocApi, ref: string): Promise<boolean> {
  try {
    if (doc.format?.highlight) {
      await Promise.resolve(doc.format.highlight({ ref, value: CITATION_HIGHLIGHT_COLOR }));
    } else if (doc.format?.apply) {
      await Promise.resolve(
        doc.format.apply({ ref, inline: { highlight: CITATION_HIGHLIGHT_COLOR } })
      );
    } else {
      return false;
    }
    activeHighlightRef = ref;
    return true;
  } catch {
    return false;
  }
}

function scrollViaSearch(instance: SuperDocInstance, pattern: string): boolean {
  const matches = instance.search(pattern);
  if (!matches?.length) return false;
  return instance.goToSearchResult(matches[0]) ?? false;
}

async function navigateWithPattern(
  instance: SuperDocInstance,
  doc: DocApi,
  pattern: string
): Promise<boolean> {
  const item = await safeQueryMatch(doc, pattern);
  const ref = item?.handle?.ref;
  if (!item || !ref) return false;

  await clearActiveHighlight(doc);

  const blockId = item.blocks?.[0]?.blockId ?? item.address?.nodeId;
  let scrolled = false;
  if (blockId) {
    try {
      scrolled = (await instance.scrollToElement(blockId)) === true;
    } catch {
      scrolled = false;
    }
  }

  const highlighted = await applyDocumentHighlight(doc, ref);
  if (scrolled && highlighted) return true;

  // Viewing mode blocks format.highlight — search navigation scrolls and highlights.
  return scrollViaSearch(instance, pattern);
}

/** Remove any citation highlight applied via the Document API. */
export async function clearDocxCitationHighlight(instance: SuperDocInstance | null): Promise<void> {
  const doc = activeDoc(instance);
  if (!doc) return;
  await clearActiveHighlight(doc);
}

/**
 * Navigate to a cited passage using the SuperDoc Document API:
 * `query.match` → `ui.viewport.scrollIntoView` → `format.highlight`.
 * Falls back to `search` / `goToSearchResult` when highlight is unavailable (e.g. viewing mode).
 */
export async function navigateToDocxCitation(
  instance: SuperDocInstance | null,
  ref: ChatReference,
  claimText?: string
): Promise<boolean> {
  if (!instance) return false;

  try {
    const patterns = citationSearchPatterns(ref, claimText);
    if (!patterns.length) return false;

    const doc = activeDoc(instance);

    if (doc?.query?.match) {
      for (const pattern of patterns) {
        if (await navigateWithPattern(instance, doc, pattern)) return true;
      }
    }

    for (const pattern of patterns) {
      if (scrollViaSearch(instance, pattern)) return true;
    }

    return false;
  } catch {
    return false;
  }
}
