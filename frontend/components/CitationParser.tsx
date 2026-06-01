"use client";

import type { ChatReference } from "@/lib/picardApi";

const MARKER = /\[(\d+)\]/g;

type Props = {
  text: string;
  references?: ChatReference[];
  onCitationClick?: (ref: ChatReference) => void;
};

export function CitationParser({ text, references = [], onCitationClick }: Props) {
  const byIndex = new Map(references.map((r) => [r.index, r]));
  const parts: React.ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  const re = new RegExp(MARKER.source, "g");
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) {
      parts.push(text.slice(last, match.index));
    }
    const idx = parseInt(match[1], 10);
    const ref = byIndex.get(idx);
    parts.push(
      <button
        key={`${match.index}-${idx}`}
        type="button"
        className="mx-0.5 inline rounded bg-neutral-200 px-1.5 py-0.5 text-xs font-medium text-neutral-800 hover:bg-neutral-300"
        onClick={() => ref && onCitationClick?.(ref)}
      >
        [{idx}]
      </button>
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <span className="whitespace-pre-wrap">{parts}</span>;
}
