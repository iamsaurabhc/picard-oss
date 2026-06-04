"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History } from "lucide-react";
import {
  picardApi,
  ChatMessage,
  ChatReference,
  ChatStreamEvent,
} from "@/lib/picardApi";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DocumentMultiSelect } from "@/components/DocumentMultiSelect";
import { useWorkspace } from "@/lib/workspaceContext";
import { NoWorkspaceState } from "@/components/NoWorkspaceState";
import { MarkdownWithCitations } from "@/components/MarkdownWithCitations";
import { RetrievalActivityPanel } from "@/components/chat/RetrievalActivityPanel";
import { ChatHistorySidebar } from "@/components/chat/ChatHistorySidebar";
import { useRetrievalActivity } from "@/components/chat/useRetrievalActivity";
import { MultiHighlightPDFViewer } from "@/components/MultiHighlightPDFViewer";
import { cn } from "@/lib/utils";

type UiMessage = {
  id?: string;
  role: string;
  content: string;
  references?: ChatReference[];
  refused?: boolean;
  suggestions?: string[];
};

function upsertAssistantMessage(
  messages: UiMessage[],
  assistant: string,
  extras?: Partial<Pick<UiMessage, "references" | "refused" | "suggestions">>
): UiMessage[] {
  const copy = [...messages];
  const last = copy[copy.length - 1];
  const msg: UiMessage = {
    role: "assistant",
    content: assistant,
    ...extras,
  };
  if (last?.role === "assistant") {
    copy[copy.length - 1] = { ...last, ...msg };
  } else {
    copy.push(msg);
  }
  return copy;
}

function mapHistoryMessage(m: ChatMessage): UiMessage {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    references: m.references ?? undefined,
    refused: m.refused,
  };
}

export default function ChatPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { workspaceId: ws, isLoading: wsLoading } = useWorkspace();
  const sessionParam = searchParams.get("session");

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [documentIds, setDocumentIds] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [activeRef, setActiveRef] = useState<ChatReference | null>(null);
  const [activeMessageRefs, setActiveMessageRefs] = useState<ChatReference[] | null>(null);
  const [pdfDocId, setPdfDocId] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [loadingThread, setLoadingThread] = useState(false);
  const [workflowId, setWorkflowId] = useState<string>("");
  const streamingRef = useRef(false);
  const initRef = useRef(false);
  const initInFlightRef = useRef(false);
  const createSessionInflightRef = useRef<Promise<string> | null>(null);
  const prevWsRef = useRef<string | null | undefined>(undefined);
  const pendingNavigationRef = useRef<string | null>(null);
  const loadThreadSeqRef = useRef(0);
  const activity = useRetrievalActivity();

  const { data: documents } = useQuery({
    queryKey: ["documents", ws],
    queryFn: () => picardApi.listDocuments(ws!),
    enabled: !!ws,
  });

  const { data: assistantWorkflows = [] } = useQuery({
    queryKey: ["workflows", ws, "assistant"],
    queryFn: () => picardApi.listWorkflows({ workspace_id: ws!, type: "assistant" }),
    enabled: !!ws,
  });

  const {
    data: sessions = [],
    isLoading: sessionsLoading,
    refetch: refetchSessions,
  } = useQuery({
    queryKey: ["chat-sessions", ws],
    queryFn: () => picardApi.listChatSessions(ws!),
    enabled: !!ws,
  });

  const loadThread = useCallback(async (id: string) => {
    if (streamingRef.current) return;
    const seq = ++loadThreadSeqRef.current;
    setLoadingThread(true);
    setMessages([]);
    try {
      const [session, hist] = await Promise.all([
        picardApi.getChatSession(id),
        picardApi.listChatMessages(id),
      ]);
      if (seq !== loadThreadSeqRef.current) return;
      setDocumentIds(session.document_ids ?? []);
      setMessages(hist.map(mapHistoryMessage));
    } catch (err) {
      if (seq !== loadThreadSeqRef.current) return;
      const detail = err instanceof Error ? err.message : "Failed to load chat";
      setMessages([{ role: "assistant", content: detail }]);
    } finally {
      if (seq === loadThreadSeqRef.current) setLoadingThread(false);
    }
  }, []);

  useEffect(() => {
    const prev = prevWsRef.current;
    if (ws === prev) return;
    prevWsRef.current = ws ?? null;

    const switchedWorkspace =
      prev !== undefined && prev !== null && ws !== null && prev !== ws;
    const clearedWorkspace = prev !== null && prev !== undefined && ws === null;

    if (!switchedWorkspace && !clearedWorkspace) {
      return;
    }

    initRef.current = false;
    initInFlightRef.current = false;
    createSessionInflightRef.current = null;
    pendingNavigationRef.current = null;
    loadThreadSeqRef.current += 1;
    setSessionId(null);
    setDocumentIds([]);
    setMessages([]);
    setPdfDocId(null);
    setActiveRef(null);
    setActiveMessageRefs(null);
    activity.reset();
    if (switchedWorkspace) {
      router.replace("/chat");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when workspace changes
  }, [ws]);

  useEffect(() => {
    if (!ws || sessionsLoading || initRef.current || initInFlightRef.current) return;
    const workspaceId = ws;
    initInFlightRef.current = true;

    let cancelled = false;

    async function resolveInitialSession() {
      let targetId: string | null = sessionParam;

      if (targetId) {
        try {
          await picardApi.getChatSession(targetId);
        } catch {
          targetId = null;
        }
      }

      if (!targetId) {
        if (!createSessionInflightRef.current) {
          createSessionInflightRef.current = picardApi
            .createChatSession({ workspace_id: workspaceId, reuse_draft: true })
            .then((created) => created.id)
            .finally(() => {
              createSessionInflightRef.current = null;
            });
        }
        targetId = await createSessionInflightRef.current;
        await refetchSessions();
      }

      if (cancelled || !targetId) {
        initInFlightRef.current = false;
        return;
      }

      initRef.current = true;
      setSessionId(targetId);
      if (targetId !== sessionParam) {
        router.replace(`/chat?session=${targetId}`);
      }
      await loadThread(targetId);
    }

    resolveInitialSession()
      .catch(() => {
        if (!initRef.current) initInFlightRef.current = false;
      })
      .finally(() => {
        if (initRef.current) initInFlightRef.current = false;
      });
    return () => {
      cancelled = true;
      if (!initRef.current) initInFlightRef.current = false;
    };
  }, [ws, sessionsLoading, sessions, sessionParam, router, loadThread, refetchSessions]);

  const selectSession = useCallback(
    async (id: string) => {
      if (streamingRef.current) return;
      pendingNavigationRef.current = id;
      setSessionId(id);
      router.replace(`/chat?session=${id}`);
      setPdfDocId(null);
      setActiveRef(null);
      setActiveMessageRefs(null);
      activity.reset();
      setHistoryOpen(false);
      await loadThread(id);
    },
    [router, activity, loadThread]
  );

  useEffect(() => {
    if (pendingNavigationRef.current && sessionParam === pendingNavigationRef.current) {
      pendingNavigationRef.current = null;
    }
  }, [sessionParam]);

  useEffect(() => {
    if (!sessionParam || !initRef.current) return;
    if (pendingNavigationRef.current) return;
    if (sessionParam === sessionId) return;
    void selectSession(sessionParam);
  }, [sessionParam, sessionId, selectSession]);

  const handleNewChat = useCallback(async () => {
    if (!ws || streamingRef.current) return;
    const onDraft = !messages.some((m) => m.role === "user");
    if (onDraft && sessionId) {
      loadThreadSeqRef.current += 1;
      setDocumentIds([]);
      setMessages([]);
      setPdfDocId(null);
      setActiveRef(null);
      setActiveMessageRefs(null);
      activity.reset();
      setHistoryOpen(false);
      return;
    }
    const draft = await picardApi.createChatSession({ workspace_id: ws, reuse_draft: true });
    await refetchSessions();
    await selectSession(draft.id);
  }, [ws, messages, sessionId, activity, refetchSessions, selectSession]);

  const handleDeleteSession = useCallback(
    async (id: string) => {
      if (!ws || streamingRef.current) return;
      await picardApi.deleteChatSession(id);
      const remaining = await refetchSessions();
      const list = remaining.data ?? [];
      if (id === sessionId) {
        if (list.length > 0) {
          await selectSession(list[0].id);
        } else {
          const created = await picardApi.createChatSession({
            workspace_id: ws,
            reuse_draft: true,
          });
          await refetchSessions();
          await selectSession(created.id);
        }
      }
    },
    [ws, sessionId, refetchSessions, selectSession, router]
  );

  const showActivityPanel = streaming || activity.steps.length > 0;

  const onSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sessionId || !ws || !input.trim() || streaming) return;
    const userText = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", content: userText }]);
    setStreaming(true);
    streamingRef.current = true;
    activity.reset();
    activity.start();
    let assistant = "";
    let refs: ChatReference[] = [];
    let refused = false;
    let suggestions: string[] = [];

    const ingestStreamEvent = (ev: ChatStreamEvent) => {
      activity.ingestEvent(ev);
      if (ev.event === "content" && "delta" in ev) {
        assistant += ev.delta;
        setMessages((m) => upsertAssistantMessage(m, assistant));
      } else if (ev.event === "references") {
        refs = ev.references ?? [];
        refused = !!ev.refused;
        suggestions = ev.suggestions ?? [];
        setMessages((m) =>
          upsertAssistantMessage(m, assistant, {
            references: refused ? undefined : refs,
            refused,
            suggestions: refused ? suggestions : undefined,
          })
        );
      }
    };

    try {
      for await (const ev of picardApi.streamChat({
        session_id: sessionId,
        workspace_id: ws,
        message: userText,
        document_ids: documentIds.length ? documentIds : undefined,
        workflow_id: workflowId || undefined,
      })) {
        if (ev.event === "error") {
          throw new Error(ev.detail);
        }
        ingestStreamEvent(ev);
      }
      setMessages((m) =>
        upsertAssistantMessage(m, assistant, {
          references: refused ? undefined : refs,
          refused,
          suggestions: refused ? suggestions : undefined,
        })
      );
      await queryClient.invalidateQueries({ queryKey: ["chat-sessions", ws] });
      const hist = await picardApi.listChatMessages(sessionId);
      setMessages(hist.map(mapHistoryMessage));
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Chat stream failed";
      setMessages((m) =>
        upsertAssistantMessage(m, assistant || detail, {
          references: assistant && refs.length ? refs : undefined,
        })
      );
    } finally {
      streamingRef.current = false;
      setStreaming(false);
      activity.finish();
    }
  };

  const activeHighlights = activeMessageRefs ?? [];
  const showPdfPanel = pdfDocId != null && activeRef != null;
  const knownDocIds = new Set((documents ?? []).map((d) => d.id));
  const scopedDocumentIds = documentIds.filter((id) => knownDocIds.has(id));

  if (wsLoading) {
    return (
      <div className="flex h-[calc(100vh)] items-center justify-center text-sm text-neutral-500">
        Loading…
      </div>
    );
  }

  if (!ws) {
    return (
      <div className="flex h-[calc(100vh)] items-center justify-center p-8">
        <NoWorkspaceState title="Select a workspace for Chat" />
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh)] flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-neutral-200 bg-white px-4 py-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="lg:hidden"
          onClick={() => setHistoryOpen((o) => !o)}
          disabled={streaming}
        >
          <History className="mr-1 h-4 w-4" />
          History
        </Button>
        <h1
          className="shrink-0 font-serif text-2xl"
          style={{ fontFamily: "var(--font-garamond), serif" }}
        >
          Chat
        </h1>
        <DocumentMultiSelect
          documents={(documents ?? []).map((d) => ({ id: d.id, file_name: d.file_name }))}
          selectedIds={scopedDocumentIds}
          onChange={setDocumentIds}
        />
        <select
          className="max-w-xs rounded border border-neutral-300 px-2 py-1.5 text-sm"
          value={workflowId}
          onChange={(e) => setWorkflowId(e.target.value)}
          title="Optional assistant workflow — pins retrieval intent and system guidance"
        >
          <option value="">No workflow</option>
          {assistantWorkflows.map((w) => (
            <option key={w.id} value={w.id}>
              {w.title}
            </option>
          ))}
        </select>
      </header>

      <div className="relative flex flex-1 overflow-hidden">
        <div
          className={cn(
            "absolute inset-y-0 left-0 z-20 lg:relative lg:z-auto",
            historyOpen ? "block" : "hidden lg:block"
          )}
        >
          <ChatHistorySidebar
            sessions={sessions}
            activeId={sessionId}
            loading={sessionsLoading}
            disabled={streaming || loadingThread}
            onSelect={selectSession}
            onNewChat={handleNewChat}
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

        <div
          className={cn(
            "grid min-w-0 flex-1 overflow-hidden",
            showPdfPanel && "grid-cols-2 divide-x divide-neutral-200"
          )}
        >
          <div className="flex flex-col overflow-hidden">
            <div className="flex-1 space-y-4 overflow-y-auto p-4">
              {loadingThread && messages.length === 0 ? (
                <p className="text-sm text-neutral-500">Loading conversation…</p>
              ) : null}
              {messages.map((m) => (
                <div
                  key={m.id ?? `${m.role}-${m.content.slice(0, 32)}`}
                  className={cn("flex w-full", m.role === "user" ? "justify-end" : "justify-start")}
                >
                  <div
                    className={cn(
                      "max-w-[85%] text-sm",
                      m.role === "user"
                        ? "rounded-2xl rounded-br-sm bg-neutral-900 px-4 py-2.5 text-neutral-50"
                        : "rounded-2xl rounded-bl-sm border border-neutral-200 bg-white px-4 py-3 text-neutral-900"
                    )}
                  >
                    {m.role === "user" ? (
                      <p className="whitespace-pre-wrap">{m.content}</p>
                    ) : m.refused ? (
                      <div>
                        <p className="font-medium text-neutral-700">No evidence found</p>
                        <MarkdownWithCitations text={m.content} className="mt-1" />
                        {m.suggestions && m.suggestions.length > 0 && (
                          <ul className="mt-2 list-disc pl-5 text-neutral-600">
                            {m.suggestions.map((s) => (
                              <li key={s}>{s}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    ) : (
                      <>
                        <MarkdownWithCitations
                          text={m.content}
                          references={m.references}
                          onCitationClick={(ref) => {
                            setActiveRef(ref);
                            setActiveMessageRefs(m.references ?? []);
                            setPdfDocId(ref.document_id);
                          }}
                        />
                        {m.references && m.references.length > 0 ? (
                          <p className="mt-2 text-xs text-neutral-500">
                            Sources ({m.references.length}) — click [{m.references[0]?.index ?? 1}]
                            {m.references.length > 1 ? "…" : ""} in the answer
                          </p>
                        ) : null}
                      </>
                    )}
                  </div>
                </div>
              ))}
              {showActivityPanel && (
                <RetrievalActivityPanel
                  steps={activity.steps}
                  stepCount={activity.stepCount}
                  isStreaming={streaming}
                  shouldMinimize={activity.shouldMinimize}
                  retrievalSummary={activity.retrievalSummary}
                />
              )}
            </div>
            <form onSubmit={onSend} className="flex gap-2 border-t border-neutral-200 p-4">
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about your documents…"
                disabled={streaming || !sessionId || loadingThread}
              />
              <Button type="submit" disabled={streaming || !sessionId || loadingThread}>
                Send
              </Button>
            </form>
          </div>

          {showPdfPanel ? (
            <MultiHighlightPDFViewer
              documentId={pdfDocId}
              highlights={activeHighlights}
              activeIndex={activeRef?.index ?? null}
              activeRef={activeRef}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
