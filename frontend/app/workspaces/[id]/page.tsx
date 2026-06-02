"use client";

import { useParams } from "next/navigation";
import { LegacyWorkspaceRedirect } from "@/components/LegacyWorkspaceRedirect";

export default function LegacyWorkspacePage() {
  const params = useParams<{ id: string }>();
  return <LegacyWorkspaceRedirect workspaceId={params.id} target="/vault" />;
}
