"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus } from "lucide-react";
import { ChatHistoryRail } from "@/components/chat/ChatHistoryRail";
import { RetrievalActivityPanel } from "@/components/chat/RetrievalActivityPanel";
import { useRetrievalActivity } from "@/components/chat/useRetrievalActivity";
import { ResizableSplitPane } from "@/components/ResizableSplitPane";
import { Button } from "@/components/ui/button";
import { useDocumentUpload } from "@/hooks/useDocumentUpload";
import { usePersistedBoolean } from "@/hooks/usePersistedBoolean";
import { useRequestTimer } from "@/hooks/useRequestTimer";
import { executeSend, upsertStreamingAssistant } from "@/lib/chatPipeline";
import {
  picardApi,
  type ChatMessage,
  type ChatReference,
  type ChatSessionSummary,
} from "@/lib/picardApi";
import type { TabularTemplateId } from "@/lib/tabular/columnPresets";
import type {
  AttachedDocument,
  ComposerMode,
  UnifiedMessage,
} from "@/lib/unifiedChatTypes";
import { attachmentsIndexing } from "@/lib/unifiedChatTypes";
import { useWorkspace } from "@/lib/workspaceContext";
import { cn } from "@/lib/utils";
import { ChatComposer } from "./ChatComposer";
import { ChatPdfPanel } from "./ChatPdfPanel";
import { ComposerScopeBar } from "./ComposerScopeBar";
import { MessageList } from "./MessageRenderer";
import { WelcomeState } from "./WelcomeState";
import "./animations.css";

function mapHistoryMessage(m: ChatMessage): UnifiedMessage {
  if (m.role === "user") {
    return { type: "user_text", id: m.id, content: m.content };
  }
  return {
    type: "assistant_qa",
    id: m.id,
    content: m.content,
    references: m.references ?? undefined,
    refused: m.refused,
  };
}

export function UnifiedChatContainer() {
  const queryClient = useQueryClient();
  const { workspaceId, workspace, isLoading: wsLoading } = useWorkspace();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UnifiedMessage[]>([]);
  const [input, setInput] = useState("");
  const [documentIds, setDocumentIds] = useState<string[]>([]);
  const [attachments, setAttachments] = useState<AttachedDocument[]>([]);
  const [mode, setMode] = useState<ComposerMode>("ask");
  const [templateId, setTemplateId] = useState<TabularTemplateId>("contract");
  const [isStreaming, setIsStreaming] = useState(false);
  const [loadingThread, setLoadingThread] = useState(false);
  const [activeRef, setActiveRef] = useState<ChatReference | null>(null);
  const [activeMessageRefs, setActiveMessageRefs] = useState<ChatReference[] | null>(null);
  const [activeClaimText, setActiveClaimText] = useState<string | null>(null);
  const [pdfDocId, setPdfDocId] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyCollapsed, setHistoryCollapsed] = usePersistedBoolean(
    "picard:chatHistoryCollapsed",
    false
  );
  const [vaultOpenRequest, setVaultOpenRequest] = useState(false);
  const [uploadTrigger, setUploadTrigger] = useState(0);

  const streamingRef = useRef(false);
  const initRef = useRef(false);
  const createSessionInflightRef = useRef<Promise<string> | null>(null);
  const prevWsRef = useRef<string | null | undefined>(undefined);

  const activity = useRetrievalActivity();
  const requestTimer = useRequestTimer();

  const { data: documents = [] } = useQuery({
    queryKey: ["documents", workspaceId],
    queryFn: () => picardApi.listDocuments(workspaceId!),
    enabled: !!workspaceId,
  });

  const { data: overview } = useQuery({
    queryKey: ["workspace-overview", workspaceId],
    queryFn: () => picardApi.getWorkspaceOverview(workspaceId!),
    enabled: !!workspaceId,
  });

  const {
    data: sessions = [],
    isLoading: sessionsLoading,
    refetch: refetchSessions,
  } = useQuery({
    queryKey: ["chat-sessions", workspaceId],
    queryFn: () => picardApi.listChatSessions(workspaceId!),
    enabled: !!workspaceId,
  });

  const indexedDocs = documents.filter((d) => d.parse_status === "done");
  const knownDocIds = new Set(documents.map((d) => d.id));
  const scopedDocumentIds = documentIds.filter((id) => knownDocIds.has(id));

  const updateAttachment = useCallback((id: string, patch: Partial<AttachedDocument>) => {
    setAttachments((prev) => prev.map((a) => (a.id === id ? { ...a, ...patch } : a)));
  }, []);

  const { uploadFiles } = useDocumentUpload(workspaceId, updateAttachment);

  const loadThread = useCallback(async (id: string) => {
    setLoadingThread(true);
    try {
      const [sess, msgs] = await Promise.all([
        picardApi.getChatSession(id),
        picardApi.listChatMessages(id),
      ]);
      setDocumentIds(sess.document_ids ?? []);
      setMessages(msgs.map(mapHistoryMessage));
    } finally {
      setLoadingThread(false);
    }
  }, []);

  useEffect(() => {
    if (!workspaceId || sessionsLoading || initRef.current) return;
    let cancelled = false;

    async function init() {
      if (!createSessionInflightRef.current) {
        createSessionInflightRef.current = picardApi
          .createChatSession({ workspace_id: workspaceId!, reuse_draft: true })
          .then((s) => s.id)
          .finally(() => {
            createSessionInflightRef.current = null;
          });
      }
      const id = await createSessionInflightRef.current;
      if (cancelled || !id) return;
      initRef.current = true;
      setSessionId(id);
      await refetchSessions();
      await loadThread(id);
    }

    void init();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, sessionsLoading, loadThread, refetchSessions]);

  useEffect(() => {
    const prev = prevWsRef.current;
    prevWsRef.current = workspaceId;

    if (prev === undefined) return;
    if (prev === workspaceId) return;

    initRef.current = false;
    createSessionInflightRef.current = null;
    setSessionId(null);
    setMessages([]);
    setDocumentIds([]);
    setAttachments([]);
    setPdfDocId(null);
    setActiveRef(null);
    setActiveMessageRefs(null);
    activity.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when workspace changes
  }, [workspaceId]);

  const handleNewChat = useCallback(async () => {
    if (!workspaceId || streamingRef.current) return;
    const hasUserMsg = messages.some((m) => m.type === "user_text");
    if (!hasUserMsg && sessionId) {
      setMessages([]);
      setDocumentIds([]);
      setAttachments([]);
      return;
    }
    const draft = await picardApi.createChatSession({ workspace_id: workspaceId, reuse_draft: true });
    await refetchSessions();
    setSessionId(draft.id);
    setMessages([]);
    setDocumentIds([]);
    setAttachments([]);
    await loadThread(draft.id);
  }, [workspaceId, messages, sessionId, refetchSessions, loadThread]);

  const selectSession = useCallback(
    async (id: string) => {
      if (streamingRef.current) return;
      setSessionId(id);
      setPdfDocId(null);
      setActiveRef(null);
      setHistoryOpen(false);
      activity.reset();
      await loadThread(id);
    },
    [loadThread, activity]
  );

  const handleDeleteSession = useCallback(
    async (id: string) => {
      if (!workspaceId || streamingRef.current) return;
      await picardApi.deleteChatSession(id);
      const remaining = await refetchSessions();
      const list = remaining.data ?? [];
      if (id === sessionId) {
        if (list.length > 0) {
          await selectSession(list[0].id);
        } else {
          const created = await picardApi.createChatSession({
            workspace_id: workspaceId,
            reuse_draft: true,
          });
          await refetchSessions();
          await selectSession(created.id);
        }
      }
    },
    [workspaceId, sessionId, refetchSessions, selectSession]
  );

  const handleUpload = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files);
      if (list.length === 0) {
        setUploadTrigger((n) => n + 1);
        return;
      }
      const added = await uploadFiles(list);
      if (added.length) setAttachments((prev) => [...prev, ...added]);
      void queryClient.invalidateQueries({ queryKey: ["documents", workspaceId] });
    },
    [uploadFiles, queryClient, workspaceId]
  );

  const ingestStreamEvent = useCallback(
    (ev: import("@/lib/picardApi").ChatStreamEvent) => {
      if (
        ev.event === "progress" ||
        ev.event === "snippet" ||
        ev.event === "retrieval" ||
        ev.event === "content"
      ) {
        activity.ingestEvent(ev);
      }
    },
    [activity]
  );

  const handleSend = useCallback(async () => {
    if (!sessionId || !workspaceId || streamingRef.current) return;
    if (mode === "ask" && !input.trim()) return;
    if (attachments.some((a) => a.status === "error")) return;

    const userText = input.trim() || (mode === "review" ? "Create tabular review" : "");
    const attachmentNames = attachments.map((a) => a.fileName);
    setInput("");
    setMessages((m) => [
      ...m,
      {
        type: "user_text",
        content: userText,
        attachmentNames: attachmentNames.length ? attachmentNames : undefined,
      },
    ]);
    setHistoryCollapsed(true);
    setIsStreaming(true);
    streamingRef.current = true;
    requestTimer.start();
    activity.reset();
    activity.start();

    const indexingBefore = attachmentsIndexing(attachments);
    if (indexingBefore) {
      setMessages((m) => [
        ...m,
        {
          type: "indexing_notice",
          documents: attachments.map((a) => ({
            id: a.id,
            name: a.fileName,
            status: a.status,
          })),
        },
      ]);
    }

    try {
      for await (const ev of executeSend(
        {
          message: userText,
          mode,
          documentIds: scopedDocumentIds,
          attachments: [...attachments],
          templateId,
          sessionId,
          workspaceId,
        },
        ingestStreamEvent
      )) {
        if (ev.type === "assistant_delta") {
          setMessages((m) => {
            const copy = [...m];
            const last = copy[copy.length - 1];
            if (last?.type === "assistant_qa" && !last.id) {
              copy[copy.length - 1] = { ...last, content: last.content + ev.delta };
            } else {
              copy.push({ type: "assistant_qa", content: ev.delta });
            }
            return copy;
          });
        } else if (ev.type === "assistant_done") {
          setMessages((m) =>
            upsertStreamingAssistant(m, ev.content, {
              references: ev.references,
              refused: ev.refused,
              suggestions: ev.suggestions,
            })
          );
        } else if (ev.type === "tabular_preview") {
          setMessages((m) => [
            ...m.filter((x) => x.type !== "indexing_notice"),
            {
              type: "tabular_preview",
              reviewId: ev.reviewId,
              title: ev.title,
              columnCount: ev.columnCount,
            },
          ]);
        } else if (ev.type === "docx_suggestion") {
          const s = ev.suggestion;
          setMessages((m) => [
            ...m.filter((x) => x.type !== "indexing_notice"),
            {
              type: "assistant_qa",
              content: `Suggested DOCX edit: replace "${s.find}" with "${s.replace}". Open the document in Vault to review and apply.`,
            },
          ]);
        } else if (ev.type === "error") {
          setMessages((m) => [
            ...m.filter((x) => x.type !== "indexing_notice"),
            { type: "error", detail: ev.detail, retry: () => setInput(userText) },
          ]);
        }
      }
      setAttachments([]);
      void queryClient.invalidateQueries({ queryKey: ["chat-sessions", workspaceId] });
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Request failed";
      setMessages((m) => [
        ...m.filter((x) => x.type !== "indexing_notice"),
        { type: "error", detail },
      ]);
    } finally {
      streamingRef.current = false;
      setIsStreaming(false);
      requestTimer.stop();
      activity.finish();
    }
  }, [
    sessionId,
    workspaceId,
    input,
    attachments,
    mode,
    scopedDocumentIds,
    templateId,
    activity,
    requestTimer,
    queryClient,
    ingestStreamEvent,
    setHistoryCollapsed,
  ]);

  const handleCitationClick = useCallback(
    (ref: ChatReference, refs: ChatReference[], claimText?: string) => {
      setActiveRef(ref);
      setActiveMessageRefs(refs);
      setActiveClaimText(claimText ?? null);
      setPdfDocId(ref.document_id ?? scopedDocumentIds[0] ?? null);
    },
    [scopedDocumentIds]
  );

  const showPdfPanel = pdfDocId != null && activeRef != null;
  const showActivityPanel = isStreaming || activity.steps.length > 0;
  const showWelcome = messages.length === 0 && !loadingThread;

  if (wsLoading) {
    return (
      <div className="flex h-[calc(100vh)] items-center justify-center text-sm text-neutral-500">
        Loading…
      </div>
    );
  }

  if (!workspaceId || !workspace) {
    return (
      <div className="flex h-[calc(100vh)] items-center justify-center text-sm text-neutral-500">
        Setting up workspace…
      </div>
    );
  }

  const mainContent = (
    <div className="chat-container flex-1">
      <header className="flex shrink-0 items-center gap-3 border-b border-neutral-200 bg-white px-4 py-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 w-8 shrink-0 p-0"
          onClick={() => void handleNewChat()}
          disabled={isStreaming || loadingThread}
          title="New chat"
          aria-label="New chat"
        >
          <MessageSquarePlus className="h-4 w-4" />
        </Button>
        <h1
          className="font-serif text-xl text-neutral-900"
          style={{ fontFamily: "var(--font-garamond), serif" }}
        >
          {workspace.name}
        </h1>
        {overview ? (
          <span className="text-xs text-neutral-500">
            {overview.documents.done} docs indexed
          </span>
        ) : null}
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto p-4">
          {showWelcome ? (
            <WelcomeState
              workspaceName={workspace.name}
              docCount={overview?.documents.done ?? 0}
              sessions={sessions as ChatSessionSummary[]}
              onSelectSession={(id) => void selectSession(id)}
              onSuggestedQuestion={setInput}
              onUploadClick={() => setUploadTrigger((n) => n + 1)}
            />
          ) : null}
          {loadingThread && messages.length === 0 ? (
            <p className="text-sm text-neutral-500">Loading conversation…</p>
          ) : null}
          <MessageList
            messages={messages}
            streaming={isStreaming}
            onCitationClick={handleCitationClick}
          />
          {showActivityPanel ? (
            <div className="mt-4">
              <RetrievalActivityPanel
                steps={activity.steps}
                stepCount={activity.stepCount}
                isStreaming={isStreaming}
                shouldMinimize={activity.shouldMinimize}
                retrievalSummary={activity.retrievalSummary}
                elapsedMs={requestTimer.elapsedMs}
              />
            </div>
          ) : null}
        </div>

        <div className="shrink-0 border-t border-neutral-200 bg-neutral-50/80 p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          <ChatComposer
            input={input}
            onInputChange={setInput}
            onSend={() => void handleSend()}
            onUpload={handleUpload}
            onBrowseVault={() => setVaultOpenRequest(true)}
            mode={mode}
            onModeChange={setMode}
            attachments={attachments}
            onRemoveAttachment={(id) => setAttachments((a) => a.filter((x) => x.id !== id))}
            isStreaming={isStreaming}
            disabled={loadingThread}
            uploadRequestId={uploadTrigger}
          />
          <ComposerScopeBar
            mode={mode}
            documents={indexedDocs.map((d) => ({ id: d.id, file_name: d.file_name }))}
            documentIds={scopedDocumentIds}
            onDocumentIdsChange={setDocumentIds}
            templateId={templateId}
            onTemplateIdChange={setTemplateId}
            vaultOpenRequest={vaultOpenRequest}
            onVaultOpenHandled={() => setVaultOpenRequest(false)}
            disabled={isStreaming}
          />
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex h-[calc(100vh)] overflow-hidden">
      <div
        className={cn(
          "absolute inset-y-0 left-0 z-20 lg:relative lg:z-auto",
          historyOpen ? "block" : "hidden lg:flex"
        )}
      >
        <ChatHistoryRail
          sessions={sessions}
          activeId={sessionId}
          loading={sessionsLoading}
          disabled={isStreaming || loadingThread}
          collapsed={historyCollapsed && !historyOpen}
          mobileOverlay={historyOpen}
          onToggleCollapse={() => {
            if (historyOpen) setHistoryOpen(false);
            else setHistoryCollapsed((c) => !c);
          }}
          onSelect={(id) => void selectSession(id)}
          onNewChat={() => void handleNewChat()}
          onDelete={handleDeleteSession}
        />
      </div>
      {historyOpen ? (
        <button
          type="button"
          aria-label="Close history"
          className="absolute inset-0 z-10 bg-black/20 lg:hidden"
          onClick={() => setHistoryOpen(false)}
        />
      ) : null}

      {showPdfPanel ? (
        <ResizableSplitPane
          direction="horizontal"
          initialRatio={0.45}
          minPrimary={280}
          minSecondary={320}
          storageKey="picard:unifiedChatPdfSplit"
          className="min-w-0 flex-1"
          primary={mainContent}
          secondary={
            <ChatPdfPanel
              documentId={pdfDocId!}
              activeRef={activeRef!}
              highlights={activeMessageRefs ?? []}
              activeClaimText={activeClaimText}
              onClose={() => {
                setPdfDocId(null);
                setActiveRef(null);
                setActiveClaimText(null);
              }}
            />
          }
        />
      ) : (
        mainContent
      )}
    </div>
  );
}
