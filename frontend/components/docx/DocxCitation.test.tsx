import { describe, expect, it } from "vitest";
import { citationSearchPattern, citationSearchPatterns } from "@/lib/docxCitation";
import type { ChatReference } from "@/lib/picardApi";

function ref(preview: string): ChatReference {
  return {
    index: 1,
    chunk_id: "c1",
    document_id: "d1",
    page: 1,
    preview,
  };
}

describe("citationSearchPattern", () => {
  it("prefers Clause label from table row excerpt", () => {
    const pattern = citationSearchPattern(
      ref(
        "[Playbook]\nSl No.: 2\nClause: Definition of Representatives\nPreferred positions: Must include affiliates"
      )
    );
    expect(pattern).toBe("Definition of Representatives");
  });

  it("builds patterns from claim text clause label", () => {
    const patterns = citationSearchPatterns(
      ref("Clause: Standstill\nPreferred positions: 6 months"),
      "Definition of Confidential Information: Accept most market language"
    );
    expect(patterns[0]).toBe("Definition of Confidential Information");
  });

  it("skips long paraphrased preferred-position excerpts", () => {
    const longPreferred =
      "The preferred position is to clearly state the entity name as MiddleGround Management with affiliates carve-out language";
    const patterns = citationSearchPatterns(
      ref(`Clause: Misc.\nPreferred positions: ${longPreferred}`)
    );
    expect(patterns.some((p) => p === longPreferred)).toBe(false);
    expect(patterns).toContain("Misc.");
  });
});
