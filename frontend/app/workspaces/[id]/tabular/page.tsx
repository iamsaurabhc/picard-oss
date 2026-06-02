"use client";

import { useParams } from "next/navigation";
import { LegacyWorkspaceRedirect } from "@/components/LegacyWorkspaceRedirect";

export default function LegacyTabularListPage() {
  const params = useParams<{ id: string }>();
  return <LegacyWorkspaceRedirect workspaceId={params.id} target="/tabular" />;
}
