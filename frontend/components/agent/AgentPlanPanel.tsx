"use client";

import { Button } from "@/components/ui/button";
import { FlowDAGPanel } from "@/components/workflows/FlowDAGPanel";
import type { WorkflowRecord } from "@/lib/picardApi";
import type { PendingApproval } from "./useAgentActivity";

type Props = {
  planText: string | null;
  workflowDraft: WorkflowRecord["flow_json"] | null;
  pendingApproval: PendingApproval | null;
  workspaceId: string | undefined;
  onApprovePlan: () => void;
  onSaveWorkflow: (title: string) => void;
};

export function AgentPlanPanel({
  planText,
  workflowDraft,
  pendingApproval,
  workspaceId,
  onApprovePlan,
  onSaveWorkflow,
}: Props) {
  if (!planText && !workflowDraft) return null;
  return (
    <div className="mb-3 space-y-2 rounded border border-neutral-200 bg-white p-3 text-sm">
      {planText && (
        <div>
          <p className="text-xs font-medium text-neutral-500">Plan</p>
          <p className="whitespace-pre-wrap text-neutral-800">{planText}</p>
        </div>
      )}
      {workflowDraft && (
        <>
          <p className="text-xs font-medium text-neutral-500">Workflow draft</p>
          <FlowDAGPanel flow={workflowDraft} />
          {pendingApproval?.kind === "plan" && (
            <Button type="button" size="sm" variant="default" onClick={onApprovePlan}>
              Approve plan (HITL-PLAN)
            </Button>
          )}
          {workspaceId && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                const title = window.prompt("Workflow title", "Agent workflow");
                if (title) onSaveWorkflow(title);
              }}
            >
              Save workflow
            </Button>
          )}
        </>
      )}
    </div>
  );
}
