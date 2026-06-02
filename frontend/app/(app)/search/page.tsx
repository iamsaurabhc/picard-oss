"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { picardApi } from "@/lib/picardApi";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/PageHeader";
import { useWorkspace } from "@/lib/workspaceContext";
import { NoWorkspaceState } from "@/components/NoWorkspaceState";
import { PageShell } from "@/components/PageShell";
import { SearchResults } from "@/components/search-results";
import { CarpDebugPanel } from "@/components/carp-debug-panel";

export default function SearchPage() {
  const { workspaceId: ws, isLoading: wsLoading } = useWorkspace();
  const [query, setQuery] = useState("liability");
  const [mode, setMode] = useState<"auto" | "simple" | "multi_constraint">("auto");
  const [partial, setPartial] = useState(false);
  const [submitted, setSubmitted] = useState<{ query: string; workspaceId: string } | null>(null);

  const { data: result, isFetching, error } = useQuery({
    queryKey: ["search", submitted, mode, partial],
    queryFn: () =>
      picardApi.search({
        query: submitted!.query,
        workspace_id: submitted!.workspaceId,
        retrieval_mode: mode,
        allow_partial_disclosure: partial,
      }),
    enabled: !!submitted?.workspaceId && !!submitted?.query,
  });

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ws) return;
    setSubmitted({ query, workspaceId: ws });
  };

  if (wsLoading) {
    return (
      <PageShell>
        <p className="text-sm text-neutral-500">Loading…</p>
      </PageShell>
    );
  }

  if (!ws) {
    return (
      <PageShell>
        <PageHeader title="Search" />
        <NoWorkspaceState title="Select a workspace for Search" />
      </PageShell>
    );
  }

  return (
    <PageShell maxWidth="4xl" className="space-y-6">
      <PageHeader
        title="Search"
        subtitle="Full-text and CARP retrieval across your workspace documents."
      />

      <form onSubmit={onSearch} className="space-y-3 rounded border border-neutral-200 bg-white p-4">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search query"
        />
        <div className="flex flex-wrap items-center gap-3">
          <select
            className="h-9 rounded border border-neutral-300 bg-white px-2 text-sm"
            value={mode}
            onChange={(e) => setMode(e.target.value as typeof mode)}
          >
            <option value="auto">auto</option>
            <option value="simple">simple</option>
            <option value="multi_constraint">multi_constraint</option>
          </select>
          <label className="flex h-9 items-center gap-1.5 text-sm">
            <input type="checkbox" checked={partial} onChange={(e) => setPartial(e.target.checked)} />
            partial disclosure
          </label>
          <Button type="submit" disabled={isFetching}>
            {isFetching ? "Searching…" : "Search"}
          </Button>
        </div>
      </form>

      {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}
      {result && (
        <>
          <div className="text-sm text-neutral-600">
            Mode: <strong>{result.mode}</strong>
            {result.refused && " · refused"}
            {result.expanded_query && (
              <span className="block text-neutral-500">Expanded: {result.expanded_query}</span>
            )}
          </div>
          <CarpDebugPanel result={result} />
          <SearchResults hits={result.hits} query={submitted?.query} />
        </>
      )}
    </PageShell>
  );
}
