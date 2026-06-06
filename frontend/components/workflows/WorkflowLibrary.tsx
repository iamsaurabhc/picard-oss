"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { picardApi, type WorkflowRecord, type WorkflowType } from "@/lib/picardApi";
import { FlowDAGPanel } from "@/components/workflows/FlowDAGPanel";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

function Tag({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "rounded border border-neutral-200 bg-neutral-50 px-2 py-0.5 text-xs text-neutral-700",
        className
      )}
    >
      {children}
    </span>
  );
}

type Props = {
  workspaceId: string;
};

export function WorkflowLibrary({ workspaceId }: Props) {
  const qc = useQueryClient();
  const [typeFilter, setTypeFilter] = useState<WorkflowType | "">("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [validationMsg, setValidationMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const { data: workflows = [], isLoading } = useQuery({
    queryKey: ["workflows", workspaceId, typeFilter],
    queryFn: () =>
      picardApi.listWorkflows({
        workspace_id: workspaceId,
        type: typeFilter || undefined,
      }),
  });

  const { data: appSettings } = useQuery({
    queryKey: ["settings"],
    queryFn: () => picardApi.getSettings(),
  });
  const agentEditEnabled =
    !!appSettings?.enable_agent_mode && !!appSettings?.agent_pack_installed;

  const selected = useMemo(
    () => workflows.find((w) => w.id === selectedId) ?? workflows[0] ?? null,
    [workflows, selectedId]
  );

  async function runValidate(w: WorkflowRecord) {
    setBusy(true);
    setValidationMsg(null);
    try {
      const r = await picardApi.validateWorkflow(w.id);
      if (r.valid) {
        const warn = r.warnings.length
          ? ` (${r.warnings.length} warning${r.warnings.length > 1 ? "s" : ""})`
          : "";
        setValidationMsg(`Valid${warn}`);
      } else {
        setValidationMsg(r.errors.map((e) => e.message).join("; "));
      }
    } catch (e) {
      setValidationMsg(e instanceof Error ? e.message : "Validation failed");
    } finally {
      setBusy(false);
    }
  }

  async function runExport(w: WorkflowRecord) {
    const data = await picardApi.exportWorkflow(w.id);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${w.id.replace(/:/g, "-")}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function runHide(w: WorkflowRecord) {
    await picardApi.hideWorkflow(w.id);
    await qc.invalidateQueries({ queryKey: ["workflows"] });
    setSelectedId(null);
  }

  if (isLoading) {
    return <p className="text-sm text-neutral-500">Loading workflows…</p>;
  }

  return (
    <div className="flex min-h-0 flex-1 gap-6">
      <div className="w-72 shrink-0 space-y-3">
        <div className="flex gap-2">
          <select
            className="w-full rounded border border-neutral-300 px-2 py-1.5 text-sm"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as WorkflowType | "")}
          >
            <option value="">All types</option>
            <option value="assistant">Assistant</option>
            <option value="tabular">Tabular</option>
            <option value="lightflow">LightFlow</option>
          </select>
        </div>
        <ul className="max-h-[calc(100vh-12rem)] space-y-1 overflow-y-auto">
          {workflows.map((w) => (
            <li key={w.id}>
              <button
                type="button"
                onClick={() => setSelectedId(w.id)}
                className={`w-full rounded px-2 py-2 text-left text-sm transition-colors ${
                  selected?.id === w.id
                    ? "bg-neutral-100 font-medium text-neutral-900"
                    : "text-neutral-600 hover:bg-neutral-50"
                }`}
              >
                {w.title}
                <span className="ml-1 text-xs text-neutral-400">({w.type})</span>
              </button>
            </li>
          ))}
        </ul>
        {!workflows.length && (
          <p className="text-sm text-neutral-500">No workflows match this filter.</p>
        )}
      </div>

      {selected ? (
        <div className="min-w-0 flex-1 space-y-4">
          <div>
            <h2 className="font-serif text-xl text-neutral-900">{selected.title}</h2>
            <div className="mt-2 flex flex-wrap gap-2">
              <Tag>{selected.type}</Tag>
              {selected.practice_area && <Tag>{selected.practice_area}</Tag>}
              <Tag>{selected.profile}</Tag>
              {selected.is_builtin && <Tag>built-in</Tag>}
            </div>
            {selected.prompt_md && (
              <p className="mt-3 whitespace-pre-wrap text-sm text-neutral-700">
                {selected.prompt_md}
              </p>
            )}
          </div>

          <FlowDAGPanel flow={selected.flow_json} />

          {selected.type === "tabular" && selected.columns_config && (
            <div>
              <h3 className="text-sm font-medium text-neutral-800">Tabular columns</h3>
              <ul className="mt-1 list-inside list-disc text-sm text-neutral-600">
                {selected.columns_config.map((c) => (
                  <li key={c.key}>{c.label}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex flex-wrap gap-2 border-t border-neutral-200 pt-4">
            <Button
              type="button"
              variant="outline"
              disabled
              title="Workflow execution ships in Phase 7b (LightFlow run)"
            >
              Run
            </Button>
            {agentEditEnabled ? (
              <Button type="button" variant="outline" asChild>
                <Link
                  href={`/chat?session=&mode=agent&workflow=${selected.id}`}
                  title="Open in Agent mode to edit or extend this playbook"
                >
                  Edit in Agent
                </Link>
              </Button>
            ) : (
              <Button
                type="button"
                variant="outline"
                disabled
                title="Enable Agent mode in Settings and install the agent pack"
              >
                Edit in Agent
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => void runValidate(selected)}
            >
              Validate
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => void runExport(selected)}
            >
              Export JSON
            </Button>
            {selected.is_builtin && (
              <Button
                type="button"
                variant="outline"
                className="text-neutral-500"
                onClick={() => void runHide(selected)}
              >
                Hide built-in
              </Button>
            )}
          </div>
          {validationMsg && (
            <p className="text-sm text-neutral-600">{validationMsg}</p>
          )}
        </div>
      ) : (
        <p className="text-sm text-neutral-500">Select a workflow to preview its DAG.</p>
      )}
    </div>
  );
}
