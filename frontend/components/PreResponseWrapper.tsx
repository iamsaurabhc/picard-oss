"use client";

type Props = {
  mode?: string;
  chunkCount?: number;
  bundleCount?: number;
  refused?: boolean;
  diagnostics?: Record<string, unknown> | null;
  loading?: boolean;
};

export function PreResponseWrapper({
  mode,
  chunkCount,
  bundleCount,
  refused,
  diagnostics,
  loading,
}: Props) {
  if (loading) {
    return (
      <div className="rounded border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-600">
        Retrieving evidence…
      </div>
    );
  }
  if (chunkCount === undefined && !refused) return null;
  return (
    <div className="rounded border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-700">
      <div className="font-medium">Retrieval</div>
      <div>
        Mode: {mode ?? "—"} · Chunks: {chunkCount ?? 0}
        {bundleCount != null && bundleCount > 0 ? ` · Bundles: ${bundleCount}` : ""}
        {refused ? " · Refused" : ""}
      </div>
      {diagnostics && Object.keys(diagnostics).length > 0 && (
        <pre className="mt-1 max-h-24 overflow-auto text-xs text-neutral-500">
          {JSON.stringify(diagnostics, null, 0)}
        </pre>
      )}
    </div>
  );
}
