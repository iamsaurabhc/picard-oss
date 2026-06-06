"use client";

import { useCallback, useState } from "react";
import type { ChatStreamEvent } from "@/lib/picardApi";
import type { WorkflowRecord } from "@/lib/picardApi";

export type ToolStep = {
  id: string;
  tool: string;
  status: "running" | "done" | "refused";
  detail?: string;
};

export type AgentPhaseStep = {
  kind: "phase";
  id: string;
  phase: string;
  label: string;
  status: "active" | "done";
};

export type PendingApproval = {
  kind: "scope" | "plan";
  token: string;
  document_ids?: string[];
  flow_json?: WorkflowRecord["flow_json"];
};

function progressLabel(ev: Extract<ChatStreamEvent, { event: "progress" }>): string {
  const { phase, status, intent, hit_count, ranked_count, documents_discovered } = ev;
  if (phase === "understanding") {
    if (status === "start") return "Understanding your question";
    const breadth = (ev as { breadth?: string }).breadth;
    const intentLabel = intent?.replace(/_/g, " ") ?? "query";
    if (breadth === "catalog") {
      return `Understood: multi-document catalog (${intentLabel})`;
    }
    if (breadth === "matter_deep") {
      return `Understood: full matter coverage (${intentLabel})`;
    }
    return `Understood: ${intentLabel}`;
  }
  if (phase === "search") {
    if (status === "start") return "Searching documents";
    if (documents_discovered != null) {
      return `Found ${documents_discovered} document${documents_discovered === 1 ? "" : "s"}`;
    }
    if (hit_count != null) return `Retrieved ${hit_count} candidate chunks`;
    return "Search complete";
  }
  if (phase === "map") {
    return status === "start" ? "Mapping per-document briefs" : "Map phase complete";
  }
  if (phase === "reduce") {
    return status === "start" ? "Synthesizing catalog" : "Reduce complete";
  }
  if (phase === "rank") {
    return status === "start" ? "Ranking evidence" : `Selected ${ranked_count ?? ""} chunks`.trim();
  }
  if (phase === "generate") {
    return status === "start" ? "Generating cited answer" : "Answer ready";
  }
  return `${phase} ${status}`;
}

function progressStepId(ev: Extract<ChatStreamEvent, { event: "progress" }>): string {
  const base = `${ev.phase}:${ev.label ?? "default"}:${ev.status}`;
  if (ev.document_id) return `${base}:${ev.document_id}`;
  return base;
}

export function useAgentActivity() {
  const [memories, setMemories] = useState<string[]>([]);
  const [toolSteps, setToolSteps] = useState<ToolStep[]>([]);
  const [phaseSteps, setPhaseSteps] = useState<AgentPhaseStep[]>([]);
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);
  const [workflowDraft, setWorkflowDraft] = useState<WorkflowRecord["flow_json"] | null>(null);
  const [planText, setPlanText] = useState<string | null>(null);

  const reset = useCallback(() => {
    setMemories([]);
    setToolSteps([]);
    setPhaseSteps([]);
    setPendingApproval(null);
    setWorkflowDraft(null);
    setPlanText(null);
  }, []);

  const ingestEvent = useCallback((ev: ChatStreamEvent) => {
    if (ev.event === "memory_hit" && "memories" in ev) {
      setMemories(ev.memories);
    } else if (ev.event === "progress") {
      const id = progressStepId(ev);
      const label = progressLabel(ev);
      setPhaseSteps((steps) => {
        const done = steps.map((s) =>
          s.kind === "phase" && s.status === "active" ? { ...s, status: "done" as const } : s
        );
        const existing = done.findIndex((s) => s.id === id);
        const row: AgentPhaseStep = {
          kind: "phase",
          id,
          phase: ev.phase,
          label,
          status: ev.status === "start" ? "active" : "done",
        };
        if (existing >= 0) {
          const copy = [...done];
          copy[existing] = row;
          return copy;
        }
        return [...done, row];
      });
    } else if (ev.event === "plan" && "plan" in ev && ev.plan) {
      setPlanText(String(ev.plan));
    } else if (ev.event === "approval_required") {
      setPendingApproval({
        kind: ev.kind,
        token: ev.token,
        document_ids: ev.document_ids,
        flow_json: ev.flow_json,
      });
      if (ev.flow_json) setWorkflowDraft(ev.flow_json);
    } else if (ev.event === "workflow_draft" && "flow_json" in ev) {
      setWorkflowDraft(ev.flow_json);
    } else if (ev.event === "tool_call") {
      const id = `${ev.tool}-${Date.now()}`;
      setToolSteps((s) => [
        ...s,
        { id, tool: ev.tool ?? "tool", status: "running", detail: JSON.stringify(ev.arguments) },
      ]);
    } else if (ev.event === "tool_result") {
      setToolSteps((s) => {
        const copy = [...s];
        let idx = copy.findIndex((t) => t.tool === ev.tool && t.status === "running");
        if (idx < 0) {
          const lastRunning = copy.map((t, i) => ({ t, i })).filter((x) => x.t.status === "running");
          idx = lastRunning.length ? lastRunning[lastRunning.length - 1].i : -1;
        }
        if (idx >= 0) {
          copy[idx] = { ...copy[idx], status: "done", detail: String(ev.output ?? "").slice(0, 200) };
        }
        return copy;
      });
    } else if (ev.event === "step_refused") {
      setToolSteps((s) => [
        ...s,
        {
          id: `refused-${Date.now()}`,
          tool: ev.tool ?? "corpus",
          status: "refused",
          detail: ev.query,
        },
      ]);
    }
  }, []);

  const clearApproval = useCallback(() => setPendingApproval(null), []);

  return {
    memories,
    toolSteps,
    phaseSteps,
    pendingApproval,
    workflowDraft,
    setWorkflowDraft,
    planText,
    reset,
    ingestEvent,
    clearApproval,
  };
};
