import assert from "node:assert/strict";
import { resolveCitationForClaim } from "./citationAnchor";
import type { ChatReference } from "@/lib/picardApi";

function ref(preview: string, chunkId: string, y0: number): ChatReference {
  return {
    index: 1,
    chunk_id: chunkId,
    document_id: "d1",
    page: 1,
    bbox: { x0: 0.1, y0, x1: 0.9, y1: y0 + 0.1 },
    preview,
  };
}

export function runCitationAnchorTests(): void {
  const party = ref(
    "Google India Private Limited Opposite Party No. 2",
    "party",
    0.7
  );
  const court = ref(
    "Case No. 39 of 2018 Competition Commission of India",
    "court",
    0.1
  );

  const claim =
    "Forum: Competition Commission of India, Case No. 39 of 2018 [1]";
  const resolved = resolveCitationForClaim(
    { ...party, page_chunks: [{ chunk_id: court.chunk_id, text: court.preview!, bbox: court.bbox }] },
    claim
  );
  assert.equal(resolved.chunk_id, "court");
  assert.equal(resolved.bbox?.y0, 0.1);

  const sameChunk = resolveCitationForClaim(
    {
      ...party,
      chunk_id: "mixed",
      page_chunks: [
        { chunk_id: "mixed", text: party.preview!, bbox: party.bbox },
        { chunk_id: "mixed", text: court.preview!, bbox: court.bbox },
      ],
    },
    claim
  );
  assert.equal(sameChunk.bbox?.y0, 0.1);
}

