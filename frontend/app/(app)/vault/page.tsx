"use client";

import { useWorkspace } from "@/lib/workspaceContext";
import { NoWorkspaceState } from "@/components/NoWorkspaceState";
import { PageShell } from "@/components/PageShell";
import { VaultDocumentsPanel } from "@/components/vault/VaultDocumentsPanel";

export default function VaultPage() {
  const { workspaceId, workspace, isLoading } = useWorkspace();

  if (isLoading) {
    return (
      <PageShell>
        <p className="text-sm text-neutral-500">Loading…</p>
      </PageShell>
    );
  }

  if (!workspaceId) {
    return (
      <PageShell>
        <NoWorkspaceState title="Select a workspace for Vault" />
      </PageShell>
    );
  }

  return <VaultDocumentsPanel workspaceId={workspaceId} workspaceName={workspace?.name} />;
}
