"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { picardApi, type ChatMessage } from "@/lib/picardApi";

export function useChatSession(workspaceId: string | null) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const sessionParam = searchParams.get("session");

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [documentIds, setDocumentIds] = useState<string[]>([]);
  const [loadingThread, setLoadingThread] = useState(false);
  const initRef = useRef(false);
  const createSessionInflightRef = useRef<Promise<string> | null>(null);
  const streamingRef = useRef(false);

  const loadThread = useCallback(async (id: string) => {
    setLoadingThread(true);
    try {
      const sess = await picardApi.getChatSession(id);
      setDocumentIds(sess.document_ids ?? []);
      const msgs = await picardApi.listChatMessages(id);
      return msgs;
    } finally {
      setLoadingThread(false);
    }
  }, []);

  const refetchSessions = useCallback(() => {
    if (!workspaceId) return Promise.resolve(undefined);
    return queryClient.refetchQueries({ queryKey: ["chat-sessions", workspaceId] });
  }, [workspaceId, queryClient]);

  useEffect(() => {
    if (!workspaceId) return;
    initRef.current = false;
    setSessionId(null);
    setDocumentIds([]);
  }, [workspaceId]);

  const mapHistory = (msgs: ChatMessage[]) => msgs;

  return {
    sessionId,
    setSessionId,
    documentIds,
    setDocumentIds,
    loadingThread,
    loadThread,
    refetchSessions,
    sessionParam,
    router,
    initRef,
    createSessionInflightRef,
    streamingRef,
    mapHistory,
  };
}
