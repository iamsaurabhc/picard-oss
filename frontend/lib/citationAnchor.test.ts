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

  // Same-doc preference: when a local same-doc match exists, do not let a
  // higher-scoring cross-document hit override it.
  const claim2 =
    "Forum: Competition Commission of India, Case No. 39 of 2018 [2]";
  const localRef: ChatReference = {
    ...party,
    index: 2,
    document_id: "doc-686",
    chunk_id: "local-686",
    page_chunks: [
      {
        chunk_id: "local-686",
        text: "Forum: Competition Commission of India, Case No. 39 of 2018 — appears in 686.pdf",
        bbox: party.bbox,
      },
    ],
  };
  const crossDocRef: ChatReference = {
    ...court,
    index: 3,
    document_id: "doc-133",
    chunk_id: "cross-133",
    page_chunks: [
      {
        chunk_id: "cross-133",
        text:
          "Forum: Competition Commission of India, Case No. 39 of 2018 — fuller phrasing from 133.pdf",
        bbox: court.bbox,
      },
    ],
  };
  const resolved2 = resolveCitationForClaim(localRef, claim2, [
    localRef,
    crossDocRef,
  ]);
  assert.equal(resolved2.document_id, "doc-686");

  // Cross-doc forced: when there is no usable local match, the returned ref
  // propagates the candidate's document_id rather than keeping the original.
  const emptyLocal: ChatReference = {
    ...party,
    index: 4,
    document_id: "doc-686",
    chunk_id: "empty-local",
    preview: "unrelated boilerplate text without the claim content",
    page_chunks: [
      {
        chunk_id: "empty-local",
        text: "unrelated boilerplate text without the claim content",
        bbox: party.bbox,
      },
    ],
  };
  const realCross: ChatReference = {
    ...court,
    index: 5,
    document_id: "doc-133",
    chunk_id: "real-cross",
    page_chunks: [
      {
        chunk_id: "real-cross",
        text:
          "Forum: Competition Commission of India, Case No. 39 of 2018 — only match across the pool",
        bbox: court.bbox,
      },
    ],
  };
  const resolved3 = resolveCitationForClaim(emptyLocal, claim, [
    emptyLocal,
    realCross,
  ]);
  assert.equal(resolved3.document_id, "doc-133");
}

