"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";

export function NoWorkspaceState({ title = "No workspace selected" }: { title?: string }) {
  return (
    <div className="mx-auto max-w-md rounded-lg border border-neutral-200 bg-white p-8 text-center">
      <h2 className="mb-2 font-serif text-lg">{title}</h2>
      <p className="mb-4 text-sm text-neutral-600">
        Select a workspace from the sidebar or create one to use this feature.
      </p>
      <Link href="/workspaces">
        <Button>Manage workspaces</Button>
      </Link>
    </div>
  );
}
