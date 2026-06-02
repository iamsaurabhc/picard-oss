"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { picardApi } from "@/lib/picardApi";
import { useWorkspace } from "@/lib/workspaceContext";
import { NoWorkspaceState } from "@/components/NoWorkspaceState";
import { PageHeader } from "@/components/PageHeader";
import { PageShell } from "@/components/PageShell";

function DashboardCard({
  title,
  subtitle,
  href,
  children,
}: {
  title: string;
  subtitle?: string;
  href: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={() => router.push(href)}
      className="flex flex-col rounded-lg border border-neutral-200 bg-white p-5 text-left shadow-sm transition-shadow hover:border-neutral-400 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-neutral-400"
    >
      <h3 className="font-serif text-lg text-neutral-900">{title}</h3>
      {subtitle ? <p className="mt-1 text-xs text-neutral-500">{subtitle}</p> : null}
      <div className="mt-3 flex-1 text-sm text-neutral-700">{children}</div>
      <span className="mt-3 text-xs font-medium text-blue-600">Open →</span>
    </button>
  );
}

export default function DashboardPage() {
  const { workspaceId, workspace, isLoading: wsLoading } = useWorkspace();

  const { data: overview, isLoading } = useQuery({
    queryKey: ["workspace-overview", workspaceId],
    queryFn: () => picardApi.getWorkspaceOverview(workspaceId!),
    enabled: !!workspaceId,
  });

  if (wsLoading) {
    return (
      <PageShell>
        <p className="text-sm text-neutral-500">Loading…</p>
      </PageShell>
    );
  }

  if (!workspaceId || !workspace) {
    return (
      <PageShell>
        <PageHeader title="Dashboard" subtitle="Your matter at a glance" />
        <div className="mt-8">
          <NoWorkspaceState />
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell maxWidth="4xl">
      <PageHeader title="Dashboard" subtitle={workspace.name} />

      {isLoading || !overview ? (
        <p className="text-sm text-neutral-500">Loading overview…</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <DashboardCard
            title="Matter profile"
            subtitle="Workspace metadata"
            href="/workspaces"
          >
            <p>
              <span className="text-neutral-500">Reference:</span>{" "}
              {overview.workspace.matter_ref ?? "—"}
            </p>
            <p className="mt-1">
              <span className="text-neutral-500">Updated:</span>{" "}
              {new Date(overview.workspace.updated_at).toLocaleDateString()}
            </p>
          </DashboardCard>

          <DashboardCard title="Vault" subtitle="Documents ingested" href="/vault">
            <p>
              {overview.documents.total} total · {overview.documents.done} indexed
            </p>
            {overview.documents.pending + overview.documents.parsing > 0 ? (
              <p className="mt-1 text-amber-700">
                {overview.documents.pending + overview.documents.parsing} in progress
              </p>
            ) : null}
            {overview.recent_documents[0] ? (
              <p className="mt-2 truncate text-xs text-neutral-500">
                Latest: {overview.recent_documents[0].file_name}
              </p>
            ) : null}
          </DashboardCard>

          <DashboardCard title="Parties" subtitle="Indexed party entities" href="/vault">
            {overview.parties.length === 0 ? (
              <p className="text-neutral-500">No parties indexed yet.</p>
            ) : (
              <ul className="space-y-1">
                {overview.parties.slice(0, 6).map((p) => (
                  <li key={p.display_value} className="truncate">
                    {p.display_value}{" "}
                    <span className="text-neutral-400">({p.document_count} docs)</span>
                  </li>
                ))}
              </ul>
            )}
          </DashboardCard>

          <DashboardCard title="Document types" subtitle="By doc_type tag" href="/vault">
            {overview.doc_types.length === 0 ? (
              <p className="text-neutral-500">No doc_type tags yet.</p>
            ) : (
              <ul className="space-y-1">
                {overview.doc_types.map((d) => (
                  <li key={d.doc_type}>
                    {d.doc_type}: {d.count}
                  </li>
                ))}
              </ul>
            )}
          </DashboardCard>

          <DashboardCard title="Tabular" subtitle="Structured reviews" href="/tabular">
            <p>{overview.tabular_reviews} review{overview.tabular_reviews === 1 ? "" : "s"}</p>
          </DashboardCard>

          <DashboardCard title="Assistant" subtitle="Chat over corpus" href="/chat">
            <p>Ask questions with citations across workspace documents.</p>
          </DashboardCard>

          <DashboardCard title="Search" subtitle="FTS and CARP retrieval" href="/search">
            <p>Run full-text and multi-constraint search across the vault.</p>
          </DashboardCard>
        </div>
      )}

      <p className="mt-8 text-sm text-neutral-500">
        <Link href="/workspaces" className="text-blue-600 hover:underline">
          Manage workspaces
        </Link>
      </p>
    </PageShell>
  );
}
