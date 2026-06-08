"use client";

import { useCallback, useRef } from "react";
import { isAcceptedDocumentFile } from "@/lib/documentTypes";
import { picardApi } from "@/lib/picardApi";
import type { AttachedDocument, AttachmentStatus } from "@/lib/unifiedChatTypes";

function mapParseStatus(parseStatus: string): AttachmentStatus {
  if (parseStatus === "done") return "ready";
  if (parseStatus === "error") return "error";
  if (parseStatus === "parsing") return "parsing";
  return "pending";
}

export function useDocumentUpload(
  workspaceId: string | null,
  onUpdate: (id: string, patch: Partial<AttachedDocument>) => void
) {
  const trackingRef = useRef<Set<string>>(new Set());

  const trackDocument = useCallback(
    async (documentId: string) => {
      if (trackingRef.current.has(documentId)) return;
      trackingRef.current.add(documentId);
      try {
        for await (const ev of picardApi.streamDocumentStatus(documentId)) {
          if (ev.event === "status") {
            onUpdate(documentId, { status: mapParseStatus(ev.parse_status) });
            if (ev.parse_error) onUpdate(documentId, { error: ev.parse_error });
          } else if (ev.event === "indexing") {
            onUpdate(documentId, { status: "indexing" });
          } else if (ev.event === "ready") {
            onUpdate(documentId, { status: "ready" });
            return;
          } else if (ev.event === "error") {
            onUpdate(documentId, { status: "error", error: ev.detail });
            return;
          }
        }
      } catch {
        try {
          const doc = await picardApi.getDocument(documentId);
          onUpdate(documentId, {
            status: mapParseStatus(doc.parse_status),
            error: doc.parse_error ?? undefined,
          });
        } catch {
          onUpdate(documentId, { status: "error", error: "Status unavailable" });
        }
      } finally {
        trackingRef.current.delete(documentId);
      }
    },
    [onUpdate]
  );

  const uploadFiles = useCallback(
    async (files: File[]) => {
      if (!workspaceId) return [] as AttachedDocument[];
      const accepted = files.filter(isAcceptedDocumentFile);
      const results: AttachedDocument[] = [];
      for (const file of accepted) {
        const doc = await picardApi.uploadDocument(workspaceId, file);
        const att: AttachedDocument = {
          id: doc.id,
          fileName: doc.file_name,
          status: mapParseStatus(doc.parse_status),
          error: doc.parse_error ?? undefined,
        };
        results.push(att);
        void trackDocument(doc.id);
      }
      return results;
    },
    [workspaceId, trackDocument]
  );

  return { uploadFiles, trackDocument };
}
