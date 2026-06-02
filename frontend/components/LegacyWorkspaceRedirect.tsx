"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useWorkspace } from "@/lib/workspaceContext";

type Props = {
  workspaceId: string;
  target: string;
};

export function LegacyWorkspaceRedirect({ workspaceId, target }: Props) {
  const router = useRouter();
  const { setWorkspaceId } = useWorkspace();

  useEffect(() => {
    setWorkspaceId(workspaceId);
    router.replace(target);
  }, [workspaceId, target, setWorkspaceId, router]);

  return (
    <div className="flex min-h-[40vh] items-center justify-center text-sm text-neutral-500">
      Redirecting…
    </div>
  );
}
