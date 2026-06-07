import type { ChatReference } from "@/lib/picardApi";

type AnchorCandidate = {
  sentence: string;
  chunk_id: string;
  bbox?: Record<string, number> | null;
  page: number;
  ref: ChatReference;
  sourceRef: ChatReference;
};

const BIND_THRESHOLD = 0.25;

function tokenSet(text: string): Set<string> {
  return new Set(
    (text.toLowerCase().match(/\w+/g) ?? []).filter((t) => t.length > 2)
  );
}

function overlapScore(claim: string, source: string): number {
  const a = tokenSet(claim);
  if (!a.size) return 0;
  const b = tokenSet(source);
  let hits = 0;
  for (const t of a) {
    if (b.has(t)) hits += 1;
  }
  return hits / a.size;
}

function phraseVariants(d1: string, d2: string): string[] {
  return [`${d1} of ${d2}`, `${d1}/${d2}`, `${d1} / ${d2}`];
}

function structuredLiteralAlignment(
  claim: string,
  chunkText: string
): number | null {
  const chunk = chunkText.toLowerCase();
  const phraseRe = /(\d+)\s+of\s+(\d+)/gi;
  const phraseGroups: string[][] = [];
  let match: RegExpExecArray | null;
  while ((match = phraseRe.exec(claim)) !== null) {
    phraseGroups.push(
      phraseVariants(match[1], match[2]).map((v) => v.toLowerCase())
    );
  }
  const dates = (claim.match(/\d{1,2}[./]\d{1,2}[./]\d{2,4}/g) ?? []).map((d) =>
    d.toLowerCase()
  );
  const required = phraseGroups.length + dates.length;
  if (!required) return null;
  let hits = phraseGroups.filter((variants) =>
    variants.some((v) => chunk.includes(v))
  ).length;
  hits += dates.filter((d) => chunk.includes(d)).length;
  return hits / required;
}

function numericTokenAlignment(claim: string, chunkText: string): number {
  const structured = structuredLiteralAlignment(claim, chunkText);
  if (structured != null) return structured;
  const digits = (claim.match(/\d+/g) ?? []).filter((d) => d.length >= 2);
  if (!digits.length) return 1;
  const hits = digits.filter((d) => chunkText.includes(d)).length;
  return hits / digits.length;
}

function scoreClaimToChunk(claim: string, chunkText: string): number {
  const needle = claim.toLowerCase().trim();
  const haystack = chunkText.toLowerCase();
  if (needle.length < 8) return 0;
  for (const length of [120, 80, 50, 30]) {
    const fragment = needle.slice(0, length);
    if (fragment.length < 8) continue;
    if (haystack.includes(fragment)) {
      return 1;
    }
  }
  // Try a middle fragment to reduce false matches on common sentence openings
  if (needle.length > 60) {
    const mid = Math.floor(needle.length / 2);
    const midFrag = needle.slice(mid - 25, mid + 25);
    if (midFrag.length >= 20 && haystack.includes(midFrag)) {
      return 0.95;
    }
  }
  const overlap = overlapScore(claim, chunkText);
  const numAlign = numericTokenAlignment(claim, chunkText);
  const hasDigits = /\d/.test(claim);
  if (hasDigits && numAlign < 1) {
    return Math.min(overlap, 0.2);
  }
  if (hasDigits && numAlign === 1) {
    return Math.max(overlap, 0.95);
  }
  return overlap;
}

function bboxKey(bbox?: Record<string, number> | null): string {
  if (!bbox) return "";
  return `${bbox.x0},${bbox.y0},${bbox.x1},${bbox.y1}`;
}

function candidatesForRef(
  ref: ChatReference,
  opts?: { includeDocBinding?: boolean; docBindingPage?: number }
): AnchorCandidate[] {
  const out: AnchorCandidate[] = [];
  const seen = new Set<string>();
  const includeDocBinding = opts?.includeDocBinding ?? false;
  const docBindingPage = opts?.docBindingPage;

  const add = (
    candidate: Omit<AnchorCandidate, "page" | "ref" | "sourceRef">,
    source: ChatReference,
    page?: number
  ) => {
    const key = `${candidate.chunk_id}:${candidate.sentence.slice(0, 40)}`;
    if (seen.has(key)) return;
    seen.add(key);
    const pageNum = page ?? source.page;
    out.push({
      ...candidate,
      page: pageNum,
      ref: { ...source, page: pageNum },
      sourceRef: source,
    });
  };

  for (const anchor of ref.sentence_anchors ?? []) {
    add(
      {
        sentence: anchor.sentence,
        chunk_id: anchor.chunk_id,
        bbox: anchor.bbox,
      },
      ref
    );
  }
  const pageChunks = ref.page_chunks ?? [];
  if (pageChunks.length) {
    for (const chunk of pageChunks) {
      add(
        {
          sentence: chunk.text,
          chunk_id: chunk.chunk_id,
          bbox: chunk.bbox,
        },
        ref
      );
    }
  } else if (ref.preview) {
    add({ sentence: ref.preview, chunk_id: ref.chunk_id, bbox: ref.bbox }, ref);
  }
  if (includeDocBinding) {
    for (const chunk of ref.document_binding_chunks ?? []) {
      if (docBindingPage != null && chunk.page !== docBindingPage) continue;
      add(
        {
          sentence: chunk.text,
          chunk_id: chunk.chunk_id,
          bbox: chunk.bbox,
        },
        ref,
        chunk.page
      );
    }
  }
  return out;
}

function pickBest(
  claim: string,
  candidates: AnchorCandidate[]
): { candidate: AnchorCandidate; score: number } | null {
  let best: AnchorCandidate | null = null;
  let bestKey: [number, number, number] = [0, 0, 0];
  for (const candidate of candidates) {
    const score = scoreClaimToChunk(claim, candidate.sentence);
    const numAlign = numericTokenAlignment(claim, candidate.sentence);
    const key: [number, number, number] = [
      score,
      numAlign,
      -candidate.sentence.length,
    ];
    if (
      key[0] > bestKey[0] ||
      (key[0] === bestKey[0] && key[1] > bestKey[1]) ||
      (key[0] === bestKey[0] && key[1] === bestKey[1] && key[2] > bestKey[2])
    ) {
      bestKey = key;
      best = candidate;
    }
  }
  const bestScore = bestKey[0];
  if (!best || bestScore < BIND_THRESHOLD) {
    return null;
  }
  return { candidate: best, score: bestScore };
}

function bestBinding(
  claim: string,
  refs: ChatReference[],
  preferRef: ChatReference
): { candidate: AnchorCandidate; score: number } | null {
  const local = pickBest(claim, candidatesForRef(preferRef));
  if (local) return local;

  // Cross-reference search: require higher confidence and prefer same document
  const CROSS_REF_THRESHOLD = 0.5;
  let best: { candidate: AnchorCandidate; score: number } | null = null;
  for (const ref of refs) {
    if (ref.index === preferRef.index) continue;
    const hit = pickBest(claim, candidatesForRef(ref));
    if (!hit || hit.score < CROSS_REF_THRESHOLD) continue;
    const sameDoc = ref.document_id === preferRef.document_id;
    const bestSameDoc = best
      ? best.candidate.sourceRef.document_id === preferRef.document_id
      : false;
    if (!best || (sameDoc && !bestSameDoc) || hit.score > best.score) {
      best = hit;
    }
  }
  if (best) return best;

  return pickBest(
    claim,
    candidatesForRef(preferRef, {
      includeDocBinding: true,
      docBindingPage: preferRef.page,
    })
  );
}

function chunksOnPage(
  page: number,
  refs: ChatReference[]
): { chunk_id: string; bbox?: Record<string, number> | null }[] {
  const out: { chunk_id: string; bbox?: Record<string, number> | null }[] = [];
  const seen = new Set<string>();
  const add = (chunk_id: string, bbox?: Record<string, number> | null) => {
    if (seen.has(chunk_id)) return;
    seen.add(chunk_id);
    out.push({ chunk_id, bbox });
  };
  for (const ref of refs) {
    for (const chunk of ref.page_chunks ?? []) {
      if (ref.page === page) add(chunk.chunk_id, chunk.bbox);
    }
    for (const chunk of ref.document_binding_chunks ?? []) {
      if (chunk.page === page) add(chunk.chunk_id, chunk.bbox);
    }
  }
  return out;
}

function paragraphHighlightBboxes(
  candidate: AnchorCandidate,
  pool: ChatReference[]
): Record<string, number>[] {
  const primary = candidate.bbox;
  if (!primary || primary.y0 == null) {
    return primary ? [primary] : [];
  }
  const pageChunks = chunksOnPage(candidate.page, pool)
    .filter((c) => c.bbox && c.bbox.y0 != null)
    .sort((a, b) => (a.bbox!.y0 as number) - (b.bbox!.y0 as number));
  const idx = pageChunks.findIndex((c) => c.chunk_id === candidate.chunk_id);
  if (idx < 0) {
    return [primary];
  }
  const MAX_EXPANSION = 3; // At most 3 chunks total (1 primary + 2 neighbors)
  const GAP_THRESHOLD = 0.025; // Tighter gap (~2.5% of page height)
  const selected = [pageChunks[idx]];
  for (let i = idx + 1; i < pageChunks.length && selected.length < MAX_EXPANSION; i++) {
    const prev = selected[selected.length - 1].bbox!;
    const cur = pageChunks[i].bbox!;
    if ((cur.y0 as number) - (prev.y1 as number) > GAP_THRESHOLD) break;
    selected.push(pageChunks[i]);
  }
  for (let i = idx - 1; i >= 0 && selected.length < MAX_EXPANSION; i--) {
    const next = selected[0].bbox!;
    const cur = pageChunks[i].bbox!;
    if ((next.y0 as number) - (cur.y1 as number) > GAP_THRESHOLD) break;
    selected.unshift(pageChunks[i]);
  }
  return selected.map((c) => c.bbox as Record<string, number>);
}

export function resolveCitationForClaim(
  ref: ChatReference,
  claimText?: string,
  contextRefs?: ChatReference[]
): ChatReference {
  if (!claimText?.trim()) {
    return ref;
  }
  const claim = claimText.replace(/\[\d+\]/g, "").trim();
  const pool = contextRefs?.length ? contextRefs : [ref];
  const binding = bestBinding(claim, pool, ref);
  if (!binding) {
    return ref;
  }

  const { candidate, score } = binding;
  const nextBbox = candidate.bbox ?? candidate.ref.bbox;
  const highlightBboxes = paragraphHighlightBboxes(candidate, pool);
  const unchanged =
    candidate.page === ref.page &&
    candidate.chunk_id === ref.chunk_id &&
    bboxKey(nextBbox) === bboxKey(ref.bbox) &&
    highlightBboxes.length <= 1;
  if (unchanged) {
    return ref;
  }

  return {
    ...ref,
    chunk_id: candidate.chunk_id,
    page: candidate.page,
    bbox: nextBbox,
    highlight_bboxes: highlightBboxes,
    pinpoint_quote: candidate.sentence.slice(0, 200),
  };
}
