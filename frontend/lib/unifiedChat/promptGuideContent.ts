import type { ComposerMode } from "@/lib/unifiedChatTypes";

export type PromptGuideSection = {
  title: string;
  body: string;
  example?: string;
};

const ASK_SECTIONS: PromptGuideSection[] = [
  {
    title: "How Picard answers",
    body:
      "Ask mode runs full-text retrieval (FTS5) and constraint-aware search (CARP), then synthesizes a cited answer with [N] markers. You get an evidence-backed response — not a raw list of search hits.",
  },
  {
    title: "Before you ask",
    body:
      "Use + to upload PDFs and wait until the attachment chip shows Ready. Use the Documents pill to limit scope — leave it on All documents to search the whole vault. Press Enter only after indexing finishes.",
  },
  {
    title: "Case overview",
    body:
      "Ask for a broad matter summary. Picard retrieves across parties, facts, damages, dates, and outcome facets.",
    example: "Summarize the parties, central facts, damages claimed, and outcome for this matter.",
  },
  {
    title: "Factual lookup",
    body:
      "Ask one specific question about a fact, figure, or clause. Name the document or page when you know it.",
    example: "What limitation period applies in the master services agreement?",
  },
  {
    title: "Listing",
    body:
      "Ask Picard to enumerate items across your scoped documents — clauses, orders, entities, or obligations.",
    example: "List all indemnity and liability-cap clauses across the selected contracts.",
  },
  {
    title: "Timeline & obligations",
    body:
      "Use timeline phrasing for chronology; use obligations phrasing for duties, requirements, and compliance terms.",
    example: "Chronology of key filing and hearing dates in these proceedings.",
  },
  {
    title: "Multi-constraint (CARP)",
    body:
      "Combine two or more constraints in one question. Picard intersects pages where all conditions appear.",
    example:
      "Find passages that mention both limitation of liability and New York governing law.",
  },
  {
    title: "After the answer",
    body:
      "Click [N] citation markers to open the PDF with highlights. If Picard refuses, no supporting evidence was found in your scoped documents — narrow or widen scope and rephrase.",
  },
];

const REVIEW_SECTIONS: PromptGuideSection[] = [
  {
    title: "What Review does",
    body:
      "Review mode creates a tabular review from your template columns — one row per document, one column per extraction field. It does not produce a chat answer.",
  },
  {
    title: "Setup",
    body:
      "Select one or more documents in the Documents pill (required). Choose a Template (Contract, NDA, etc.) that defines the columns Picard will fill.",
  },
  {
    title: "Send",
    body:
      "Your message can be empty — Picard uses the template default title. Or type a custom review title or short instructions.",
    example: "Q1 vendor contract comparison",
  },
  {
    title: "Next step",
    body:
      "After creation, open the full review grid to run cell generation, edit prompts, and export. Use Ask mode if you need a conversational cited answer instead.",
  },
];

export function getPromptGuideSections(mode: ComposerMode): PromptGuideSection[] {
  return mode === "review" ? REVIEW_SECTIONS : ASK_SECTIONS;
}
