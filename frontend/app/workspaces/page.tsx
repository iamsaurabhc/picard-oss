"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/PageHeader";
import { PageShell } from "@/components/PageShell";
import { picardApi } from "@/lib/picardApi";
import { useWorkspace } from "@/lib/workspaceContext";

export default function WorkspacesPage() {
  const qc = useQueryClient();
  const { setWorkspaceId } = useWorkspace();
  const [name, setName] = useState("");
  const { data: workspaces = [], isLoading } = useQuery({
    queryKey: ["workspaces"],
    queryFn: picardApi.listWorkspaces,
  });
  const create = useMutation({
    mutationFn: () => picardApi.createWorkspace({ name }),
    onSuccess: (ws) => {
      setName("");
      setWorkspaceId(ws.id);
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });

  return (
    <PageShell maxWidth="3xl">
      <PageHeader
        title="Manage workspaces"
        subtitle="Create matters and switch the active workspace from the sidebar selector."
      />
      <div className="mb-8 flex gap-2">
        <Input placeholder="Matter name" value={name} onChange={(e) => setName(e.target.value)} />
        <Button disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
          Create
        </Button>
      </div>
      {isLoading ? (
        <p className="text-sm text-neutral-500">Loading…</p>
      ) : (
        <ul className="divide-y divide-neutral-200 rounded border border-neutral-200 bg-white">
          {workspaces.map((ws) => (
            <li key={ws.id} className="flex items-center justify-between px-4 py-3">
              <div>
                <Link
                  href="/"
                  className="font-medium hover:underline"
                  onClick={() => setWorkspaceId(ws.id)}
                >
                  {ws.name}
                </Link>
                {ws.matter_ref ? <p className="text-xs text-neutral-500">CM: {ws.matter_ref}</p> : null}
              </div>
              <span className="text-xs text-neutral-400">{new Date(ws.updated_at).toLocaleDateString()}</span>
            </li>
          ))}
          {workspaces.length === 0 ? (
            <li className="px-4 py-8 text-center text-sm text-neutral-500">No workspaces yet.</li>
          ) : null}
        </ul>
      )}
    </PageShell>
  );
}
