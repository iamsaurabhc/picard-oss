"use client";

import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { useWorkspace } from "@/lib/workspaceContext";
import { cn } from "@/lib/utils";

function workspaceInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

type Props = {
  collapsed?: boolean;
};

export function WorkspaceSelector({ collapsed = false }: Props) {
  const { workspaceId, workspace, workspaces, setWorkspaceId, isLoading, isError } = useWorkspace();
  const [open, setOpen] = useState(false);

  const label = isLoading
    ? "Loading…"
    : isError
      ? "API unavailable"
      : (workspace?.name ?? "Select workspace");

  const dropdown = open ? (
    <>
      <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
      <div
        className={cn(
          "absolute z-50 mt-1 max-h-56 overflow-y-auto rounded border border-neutral-200 bg-white py-1 shadow-lg",
          collapsed ? "left-0 w-56" : "left-0 right-0 top-full"
        )}
        style={collapsed ? { top: "100%" } : undefined}
      >
        {workspaces.length === 0 ? (
          <p className="px-3 py-2 text-xs text-neutral-500">No workspaces</p>
        ) : (
          workspaces.map((ws) => (
            <button
              key={ws.id}
              type="button"
              className={`block w-full px-3 py-2 text-left text-sm hover:bg-neutral-50 ${
                ws.id === workspaceId ? "bg-neutral-100 font-medium" : ""
              }`}
              onClick={() => {
                setWorkspaceId(ws.id);
                setOpen(false);
              }}
            >
              <span className="block truncate">{ws.name}</span>
              {ws.matter_ref ? (
                <span className="text-xs text-neutral-500">CM: {ws.matter_ref}</span>
              ) : null}
            </button>
          ))
        )}
        <div className="mt-1 border-t border-neutral-100 pt-1">
          <Link
            href="/workspaces"
            className="block px-3 py-2 text-xs text-neutral-600 hover:bg-neutral-50"
            onClick={() => setOpen(false)}
          >
            Manage workspaces
          </Link>
        </div>
      </div>
    </>
  ) : null;

  if (collapsed) {
    return (
      <div className="relative mb-4 flex justify-center">
        <button
          type="button"
          className="flex h-9 w-9 items-center justify-center rounded-full border border-neutral-200 bg-neutral-50 text-xs font-medium text-neutral-700 hover:bg-neutral-100"
          onClick={() => setOpen((o) => !o)}
          disabled={isLoading}
          title={label}
          aria-label={`Workspace: ${label}`}
        >
          {workspace?.name ? workspaceInitials(workspace.name) : "?"}
        </button>
        {dropdown}
      </div>
    );
  }

  return (
    <div className="relative mb-4">
      <button
        type="button"
        className="flex w-full items-center justify-between rounded border border-neutral-200 bg-neutral-50 px-2 py-2 text-left text-sm hover:bg-neutral-100"
        onClick={() => setOpen((o) => !o)}
        disabled={isLoading}
      >
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <ChevronDown className="ml-1 h-4 w-4 shrink-0 text-neutral-500" />
      </button>
      {workspace?.matter_ref ? (
        <p className="mt-1 truncate px-1 text-xs text-neutral-500">CM: {workspace.matter_ref}</p>
      ) : null}
      {dropdown}
    </div>
  );
}
