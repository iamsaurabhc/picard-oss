import { SearchHit } from "@/lib/picardApi";

function BreadcrumbChips({ path }: { path: string | null }) {
  if (!path) return <span className="text-neutral-400">—</span>;
  const parts = path.split(">").map((p) => p.trim()).filter(Boolean);
  if (parts.length === 0) return <span className="text-neutral-400">—</span>;

  const maxVisible = 3;
  const visible = parts.length > maxVisible ? parts.slice(-maxVisible) : parts;
  const hidden = parts.length - visible.length;

  return (
    <span className="flex flex-wrap items-center justify-end gap-1">
      {hidden > 0 && (
        <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs text-neutral-500">…</span>
      )}
      {visible.map((part, i) => (
        <span
          key={`${i}-${part}`}
          className="max-w-[120px] truncate rounded bg-neutral-100 px-1.5 py-0.5 text-xs text-neutral-600"
          title={part}
        >
          {part}
        </span>
      ))}
    </span>
  );
}

function normalizeText(text: string): string {
  return text.replace(/\n+/g, " ").replace(/\s+/g, " ").trim();
}

function highlightQuery(text: string, query?: string): React.ReactNode {
  if (!query?.trim()) return text;
  const terms = query.trim().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return text;

  const pattern = new RegExp(
    `(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`,
    "gi"
  );
  const parts = text.split(pattern);
  const lowerTerms = new Set(terms.map((t) => t.toLowerCase()));
  return parts.map((part, i) =>
    lowerTerms.has(part.toLowerCase()) ? (
      <mark key={i} className="rounded bg-amber-100 px-0.5">
        {part}
      </mark>
    ) : (
      part
    )
  );
}

type Props = {
  hits: SearchHit[];
  query?: string;
};

export function SearchResults({ hits, query }: Props) {
  if (!hits.length) {
    return <p className="text-sm text-neutral-500">No hits.</p>;
  }
  return (
    <ul className="space-y-3">
      {hits.map((hit) => (
        <li key={hit.chunk_id} className="rounded border border-neutral-200 bg-white p-3 text-sm">
          <div className="mb-2 flex items-start justify-between gap-3 text-xs text-neutral-500">
            <span className="shrink-0">
              p.{hit.page_number} · score {hit.score.toFixed(2)}
            </span>
            <BreadcrumbChips path={hit.heading_path} />
          </div>
          <p className="line-clamp-4 text-neutral-800">
            {highlightQuery(normalizeText(hit.text_content), query)}
          </p>
        </li>
      ))}
    </ul>
  );
}
