"use client";

import { useWorkspace } from "@/lib/workspaceContext";
import { NoWorkspaceState } from "@/components/NoWorkspaceState";
import { WorkflowLibrary } from "@/components/workflows/WorkflowLibrary";

export default function WorkflowsPage() {
  const { workspaceId } = useWorkspace();

  if (!workspaceId) {
    return <NoWorkspaceState />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col p-6">
      <h1 className="font-serif text-2xl text-neutral-900">Workflow library</h1>
      <p className="mt-1 text-sm text-neutral-600">
        Evidence-aware playbooks with LightFlow DAG specs. Run and agent editing arrive in Phase
        7.
      </p>
      <div className="mt-6 min-h-0 flex-1">
        <WorkflowLibrary workspaceId={workspaceId} />
      </div>
    </div>
  );
}
