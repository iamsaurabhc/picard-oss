import { SearchResponse } from "@/lib/picardApi";

export function CarpDebugPanel({ result }: { result: SearchResponse }) {
  const diag = result.retrieval_diagnostics;
  if (!diag && !result.bundles?.length) return null;

  return (
    <details className="rounded border border-neutral-200 bg-neutral-50 p-3 text-sm" open>
      <summary className="cursor-pointer font-medium">CARP debug</summary>
      <div className="mt-2 space-y-2">
        {result.proximity_tier_used && (
          <p>
            Proximity tier: <code>{result.proximity_tier_used}</code>
          </p>
        )}
        {diag && (
          <pre className="overflow-x-auto rounded bg-white p-2 text-xs">
            {JSON.stringify(diag, null, 2)}
          </pre>
        )}
        {result.bundles?.map((b) => (
          <div key={b.bundle_id} className="rounded border border-neutral-200 bg-white p-2 text-xs">
            <p>
              Bundle p.{b.page_start} · score {b.score.toFixed(3)} · {b.proximity_tier}
            </p>
            <p>Matched: {b.constraints_matched.join(", ") || "—"}</p>
            {b.constraints_missing.length > 0 && (
              <p className="text-amber-700">Missing: {b.constraints_missing.join(", ")}</p>
            )}
          </div>
        ))}
        {(result.suggestions?.length ?? 0) > 0 && (
          <ul className="list-disc pl-4 text-neutral-600">
            {result.suggestions!.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}
