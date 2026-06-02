"use client";

import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { picardApi, type DocumentRecord } from "@/lib/picardApi";

export function usePollingDocuments(workspaceId: string | null) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["documents", workspaceId],
    queryFn: () => picardApi.listDocuments(workspaceId!),
    enabled: !!workspaceId,
    refetchInterval: (q) => {
      const docs = q.state.data as DocumentRecord[] | undefined;
      const active = docs?.some((d) => d.parse_status === "pending" || d.parse_status === "parsing");
      return active ? 2000 : false;
    },
  });

  useEffect(() => {
    if (!workspaceId) return;
    const docs = query.data;
    if (!docs) return;
    const pending = docs.filter((d) => d.parse_status === "pending" || d.parse_status === "parsing");
    pending.forEach((d) => {
      picardApi.getDocument(d.id).then((fresh) => {
        qc.setQueryData<DocumentRecord[]>(["documents", workspaceId], (old) =>
          old?.map((row) => (row.id === fresh.id ? fresh : row))
        );
      });
    });
  }, [query.data, workspaceId, qc]);

  return query;
}
