"use client";

import { useParams } from "next/navigation";
import { LegacyWorkspaceRedirect } from "@/components/LegacyWorkspaceRedirect";

export default function LegacyTabularReviewPage() {
  const params = useParams<{ id: string; reviewId: string }>();
  return (
    <LegacyWorkspaceRedirect workspaceId={params.id} target={`/tabular/${params.reviewId}`} />
  );
}
