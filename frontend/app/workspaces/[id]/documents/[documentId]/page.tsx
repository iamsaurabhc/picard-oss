"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

export default function LegacyDocumentPage() {
  const params = useParams<{ id: string; documentId: string }>();
  const router = useRouter();

  useEffect(() => {
    router.replace(`/vault/${params.documentId}`);
  }, [params.documentId, router]);

  return (
    <div className="flex min-h-[40vh] items-center justify-center text-sm text-neutral-500">
      Redirecting…
    </div>
  );
}
