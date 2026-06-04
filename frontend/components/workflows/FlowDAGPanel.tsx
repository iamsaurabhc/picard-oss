"use client";

import type { WorkflowRecord } from "@/lib/picardApi";

type Props = {
  flow: WorkflowRecord["flow_json"];
  className?: string;
};

export function FlowDAGPanel({ flow, className }: Props) {
  const steps = flow.steps ?? [];
  const order = topologicalOrder(steps);

  return (
    <div className={className}>
      <p className="mb-2 text-xs text-neutral-500">
        LightFlow v{flow.version}
        {flow.input_hint ? ` · ${flow.input_hint}` : ""}
      </p>
      <ol className="space-y-2">
        {order.map((name) => {
          const step = steps.find((s) => s.name === name);
          if (!step) return null;
          const deps = step.depends_on?.length
            ? `← ${step.depends_on.join(", ")}`
            : null;
          return (
            <li
              key={step.name}
              className="rounded border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-neutral-900">{step.name}</span>
                <span className="rounded bg-neutral-200 px-1.5 py-0.5 text-xs text-neutral-700">
                  {step.role}
                </span>
                {step.refuse_on_empty && (
                  <span className="text-xs text-amber-700">refuse_on_empty</span>
                )}
              </div>
              {deps && <p className="mt-1 text-xs text-neutral-500">{deps}</p>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function topologicalOrder(
  steps: WorkflowRecord["flow_json"]["steps"]
): string[] {
  const names = steps.map((s) => s.name);
  const set = new Set(names);
  const indegree: Record<string, number> = Object.fromEntries(names.map((n) => [n, 0]));
  const adj: Record<string, string[]> = Object.fromEntries(names.map((n) => [n, []]));
  for (const step of steps) {
    for (const dep of step.depends_on ?? []) {
      if (!set.has(dep)) continue;
      indegree[step.name] = (indegree[step.name] ?? 0) + 1;
      adj[dep].push(step.name);
    }
  }
  const queue = names.filter((n) => indegree[n] === 0);
  const out: string[] = [];
  while (queue.length) {
    const n = queue.shift()!;
    out.push(n);
    for (const child of adj[n]) {
      indegree[child] -= 1;
      if (indegree[child] === 0) queue.push(child);
    }
  }
  return out.length === names.length ? out : names;
}
