"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History, MessageSquarePlus } from "lucide-react";
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
import { ChatHistoryRail } from "@/components/chat/ChatHistoryRail";
import { useRetrievalActivity } from "@/components/chat/useRetrievalActivity";
import { AgentPlanPanel } from "@/components/agent/AgentPlanPanel";
import { MemoryHitChip } from "@/components/agent/MemoryHitChip";
import { ModeToggle } from "@/components/agent/ModeToggle";
import { ScopeConfirmBar } from "@/components/agent/ScopeConfirmBar";
import { ToolTimeline } from "@/components/agent/ToolTimeline";
import { useAgentActivity } from "@/components/agent/useAgentActivity";
import { ChatPdfPanel } from "@/components/unified-chat/ChatPdfPanel";
import { ResizableSplitPane } from "@/components/ResizableSplitPane";
import { usePersistedBoolean } from "@/hooks/usePersistedBoolean";
import { resolveCitationForClaim } from "@/lib/citationAnchor";
import { useRequestTimer } from "@/hooks/useRequestTimer";
import { isDevTestMode } from "@/lib/featureFlags";
import { cn } from "@/lib/utils";
import {
  PiiInfoBanner,
  PiiProtectionToggle,
  PII_INFO_DISMISSED_KEY,
  readPiiPreference,
} from "@/components/chat/PiiProtectionToggle";

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

function dedupeHistoryMessages(msgs: UiMessage[]): UiMessage[] {
  const out: UiMessage[] = [];
  for (const m of msgs) {
    const prev = out[out.length - 1];
    if (prev && prev.role === "user" && m.role === "user" && prev.content === m.content) {
      continue;
    }
    out.push(m);
  }
  return out;
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
  const [activeClaimText, setActiveClaimText] = useState<string | null>(null);
  const [pdfDocId, setPdfDocId] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyCollapsed, setHistoryCollapsed] = usePersistedBoolean("picard:chatHistoryCollapsed", false);
  const [loadingThread, setLoadingThread] = useState(false);
  const streamingRef = useRef(false);
  const initRef = useRef(false);
  const initInFlightRef = useRef(false);
  const createSessionInflightRef = useRef<Promise<string> | null>(null);
  const prevWsRef = useRef<string | null | undefined>(undefined);
  const pendingNavigationRef = useRef<string | null>(null);
  const loadThreadSeqRef = useRef(0);
  const activity = useRetrievalActivity();
  const agentActivity = useAgentActivity();
  const requestTimer = useRequestTimer();
  const modeParam = searchParams.get("mode");
  const [chatMode, setChatMode] = useState<"rag" | "agent">(
    modeParam === "agent" ? "agent" : "rag"
  );
  const [piiEnabled, setPiiEnabled] = useState(true);
  const [piiInfoDismissed, setPiiInfoDismissed] = useState(true);

  const { data: appSettings } = useQuery({
    queryKey: ["settings"],
    queryFn: () => picardApi.getSettings(),
  });
  const agentModeOn = !!appSettings?.enable_agent_mode;
  const agentPackReady = !!appSettings?.agent_pack_installed;
  const agentChatReady = agentModeOn && agentPackReady;
  const effectiveMode: "rag" | "agent" =
    isDevTestMode && chatMode === "agent" ? "agent" : "rag";

  useEffect(() => {
    if (!appSettings) return;
    const defaultOn =
      appSettings.enable_pii_protection_default ?? true;
    setPiiEnabled(readPiiPreference(defaultOn));
    setPiiInfoDismissed(localStorage.getItem(PII_INFO_DISMISSED_KEY) === "true");
  }, [appSettings]);

  const { data: documents } = useQuery({
    queryKey: ["documents", ws],
    queryFn: () => picardApi.listDocuments(ws!),
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
      setMessages(dedupeHistoryMessages(hist.map(mapHistoryMessage)));
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

  const collapseHistory = useCallback(() => {
    setHistoryCollapsed(true);
    setHistoryOpen(false);
  }, [setHistoryCollapsed]);

  const toggleHistoryDesktop = useCallback(() => {
    setHistoryCollapsed((c) => !c);
  }, [setHistoryCollapsed]);

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
      collapseHistory();
      return;
    }
    const draft = await picardApi.createChatSession({ workspace_id: ws, reuse_draft: true });
    await refetchSessions();
    await selectSession(draft.id);
  }, [ws, messages, sessionId, activity, refetchSessions, selectSession, collapseHistory]);

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

  const showActivityPanel =
    streaming || activity.steps.length > 0;
  const showAgentToolsPanel =
    effectiveMode === "agent" &&
    (agentActivity.toolSteps.length > 0 || !!agentActivity.workflowDraft);

  useEffect(() => {
    if (modeParam === "agent" && agentChatReady && isDevTestMode) setChatMode("agent");
  }, [modeParam, agentChatReady]);

  const runStream = async (
    message: string,
    extra?: { approval_token?: string }
  ) => {
    let assistant = "";
    let refs: ChatReference[] = [];
    let refused = false;
    let suggestions: string[] = [];
    let streamBuffer = "";
    let flushTimer: ReturnType<typeof setTimeout> | null = null;

    const flushStreamBuffer = () => {
      if (!streamBuffer) return;
      assistant += streamBuffer;
      streamBuffer = "";
      setMessages((m) => upsertAssistantMessage(m, assistant));
    };

    const scheduleFlush = () => {
      if (flushTimer) return;
      flushTimer = setTimeout(() => {
        flushTimer = null;
        flushStreamBuffer();
      }, 75);
    };

    const ingestStreamEvent = (ev: ChatStreamEvent) => {
      if (
        ev.event === "progress" ||
        ev.event === "snippet" ||
        ev.event === "retrieval" ||
        ev.event === "content"
      ) {
        activity.ingestEvent(ev);
      }
      if (effectiveMode === "agent") {
        agentActivity.ingestEvent(ev);
      }
      if (ev.event === "content" && "delta" in ev) {
        streamBuffer += ev.delta;
        scheduleFlush();
      } else if (ev.event === "references") {
        if (flushTimer) {
          clearTimeout(flushTimer);
          flushTimer = null;
        }
        flushStreamBuffer();
        refs = ev.references ?? [];
        if (typeof ev.content === "string" && ev.content.length > 0) {
          assistant = ev.content;
        }
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

    for await (const ev of picardApi.streamChat({
      session_id: sessionId!,
      workspace_id: ws!,
      message,
      mode: effectiveMode,
      document_ids: documentIds.length ? documentIds : undefined,
      approval_token: extra?.approval_token,
      enable_pii_protection:
        appSettings?.llm_provider === "ollama" ? false : piiEnabled,
    })) {
      const errMsg =
        ev.event === "error"
          ? ("detail" in ev && ev.detail) || ("message" in ev && ev.message) || "Error"
          : null;
      if (errMsg) throw new Error(String(errMsg));
      ingestStreamEvent(ev);
    }
    if (flushTimer) {
      clearTimeout(flushTimer);
    }
    flushStreamBuffer();
    setMessages((m) =>
      upsertAssistantMessage(m, assistant, {
        references: refused ? undefined : refs,
        refused,
        suggestions: refused ? suggestions : undefined,
      })
    );
    void queryClient.invalidateQueries({ queryKey: ["chat-sessions", ws] });
  };

  const onSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sessionId || !ws || !input.trim() || streaming) return;
    const userText = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", content: userText }]);
    collapseHistory();
    setStreaming(true);
    streamingRef.current = true;
    requestTimer.start();
    activity.reset();
    activity.start();
    if (effectiveMode === "agent") {
      agentActivity.reset();
    }

    try {
      await runStream(userText);
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Chat stream failed";
      setMessages((m) => upsertAssistantMessage(m, detail));
    } finally {
      streamingRef.current = false;
      setStreaming(false);
      requestTimer.stop();
      activity.finish();
    }
  };

  const handleApproveScope = async () => {
    const approval = agentActivity.pendingApproval;
    if (!approval || !sessionId || !ws) return;
    agentActivity.clearApproval();
    setStreaming(true);
    streamingRef.current = true;
    try {
      await runStream("Approved document scope.", { approval_token: approval.token });
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Approval failed";
      setMessages((m) => [...m, { role: "assistant", content: detail }]);
    } finally {
      streamingRef.current = false;
      setStreaming(false);
    }
  };

  const handleSaveWorkflow = async (title: string) => {
    if (!ws || !agentActivity.workflowDraft) return;
    await picardApi.createWorkflow({
      workspace_id: ws,
      type: "lightflow",
      title,
      flow_json: agentActivity.workflowDraft,
      evidence_profile: { requires_corpus: true, allows_tabular: true },
      profile: appSettings?.agent_profile === "court" ? "court" : "firm",
    });
    await queryClient.invalidateQueries({ queryKey: ["workflows", ws] });
  };

  const activeHighlights = activeMessageRefs ?? [];
  const showPdfPanel = pdfDocId != null && activeRef != null;

  useEffect(() => {
    if (showPdfPanel) {
      collapseHistory();
    }
  }, [showPdfPanel, collapseHistory]);

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
          className="h-8 w-8 shrink-0 p-0"
          onClick={() => void handleNewChat()}
          disabled={streaming || loadingThread}
          title="New chat"
          aria-label="New chat"
        >
          <MessageSquarePlus className="h-4 w-4" />
        </Button>
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
          {effectiveMode === "agent" ? "Agent" : "Chat"}
        </h1>
        {isDevTestMode && agentModeOn ? (
          <span
            title={
              agentPackReady
                ? undefined
                : "Install the agent pack in Settings, then restart the API."
            }
          >
            <ModeToggle
              mode={chatMode}
              disabled={streaming}
              onChange={(m) => {
                if (m === "agent" && !agentPackReady) return;
                setChatMode(m);
                if (m === "rag") agentActivity.reset();
              }}
            />
          </span>
        ) : null}
        <DocumentMultiSelect
          documents={(documents ?? []).map((d) => ({ id: d.id, file_name: d.file_name }))}
          selectedIds={scopedDocumentIds}
          onChange={setDocumentIds}
        />
        {appSettings ? (
          <PiiProtectionToggle
            llmProvider={appSettings.llm_provider}
            defaultEnabled={appSettings.enable_pii_protection_default ?? true}
            disabled={streaming}
            enabled={piiEnabled}
            onChange={setPiiEnabled}
          />
        ) : null}
      </header>

      <div className="relative flex flex-1 overflow-hidden">
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
            disabled={streaming || loadingThread}
            collapsed={historyCollapsed && !historyOpen}
            mobileOverlay={historyOpen}
            onToggleCollapse={() => {
              if (historyOpen) {
                setHistoryOpen(false);
              } else {
                toggleHistoryDesktop();
              }
            }}
            onSelect={(id) => {
              void selectSession(id);
              setHistoryOpen(false);
            }}
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
            storageKey="picard:chatPdfSplit"
            className="min-w-0 flex-1"
            primary={
              <div className="flex h-full flex-col overflow-hidden">
                <div className="flex-1 space-y-4 overflow-y-auto p-4">
              {effectiveMode === "agent" && (
                <>
                  <MemoryHitChip memories={agentActivity.memories} />
                  {agentActivity.pendingApproval?.kind === "scope" && (
                    <ScopeConfirmBar
                      approval={agentActivity.pendingApproval}
                      onApprove={() => void handleApproveScope()}
                      onDeny={agentActivity.clearApproval}
                    />
                  )}
                  <AgentPlanPanel
                    planText={agentActivity.planText}
                    workflowDraft={agentActivity.workflowDraft}
                    pendingApproval={agentActivity.pendingApproval}
                    workspaceId={ws}
                    onApprovePlan={() => {
                      const t = agentActivity.pendingApproval?.token;
                      if (t) void runStream("Approve workflow plan.", { approval_token: t });
                    }}
                    onSaveWorkflow={(title) => void handleSaveWorkflow(title)}
                  />
                </>
              )}
              {loadingThread && messages.length === 0 ? (
                <p className="text-sm text-neutral-500">Loading conversation…</p>
              ) : null}
              {messages.map((m) => {
                if (m.role === "assistant" && !m.content && !m.refused && streaming) {
                  return null;
                }
                return (
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
                          onCitationClick={(ref, claimText) => {
                            const resolved = resolveCitationForClaim(
                              ref,
                              claimText,
                              m.references ?? undefined
                            );
                            setActiveRef(resolved);
                            setActiveMessageRefs(m.references ?? [resolved]);
                            setActiveClaimText(claimText ?? null);
                            setPdfDocId(resolved.document_id ?? documentIds[0] ?? null);
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
              );
              })}
              {showActivityPanel && (
                <RetrievalActivityPanel
                  steps={activity.steps}
                  stepCount={activity.stepCount}
                  isStreaming={streaming}
                  shouldMinimize={activity.shouldMinimize}
                  retrievalSummary={activity.retrievalSummary}
                  elapsedMs={requestTimer.elapsedMs}
                />
              )}
              {showAgentToolsPanel ? (
                <div className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2">
                  <ToolTimeline steps={agentActivity.toolSteps} />
                </div>
              ) : null}
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
            }
            secondary={
              activeRef ? (
                <ChatPdfPanel
                  documentId={pdfDocId!}
                  activeRef={activeRef}
                  highlights={activeHighlights}
                  activeClaimText={activeClaimText}
                  onClose={() => {
                    setPdfDocId(null);
                    setActiveRef(null);
                    setActiveClaimText(null);
                  }}
                />
              ) : null
            }
          />
        ) : (
          <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
            <div className="flex-1 space-y-4 overflow-y-auto p-4">
              {effectiveMode === "agent" && (
                <>
                  <MemoryHitChip memories={agentActivity.memories} />
                  {agentActivity.pendingApproval?.kind === "scope" && (
                    <ScopeConfirmBar
                      approval={agentActivity.pendingApproval}
                      onApprove={() => void handleApproveScope()}
                      onDeny={agentActivity.clearApproval}
                    />
                  )}
                  <AgentPlanPanel
                    planText={agentActivity.planText}
                    workflowDraft={agentActivity.workflowDraft}
                    pendingApproval={agentActivity.pendingApproval}
                    workspaceId={ws}
                    onApprovePlan={() => {
                      const t = agentActivity.pendingApproval?.token;
                      if (t) void runStream("Approve workflow plan.", { approval_token: t });
                    }}
                    onSaveWorkflow={(title) => void handleSaveWorkflow(title)}
                  />
                </>
              )}
              {loadingThread && messages.length === 0 ? (
                <p className="text-sm text-neutral-500">Loading conversation…</p>
              ) : null}
              {messages.map((m) => {
                if (m.role === "assistant" && !m.content && !m.refused && streaming) {
                  return null;
                }
                return (
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
                            onCitationClick={(ref, claimText) => {
                              const resolved = resolveCitationForClaim(
                                ref,
                                claimText,
                                m.references ?? undefined
                              );
                              setActiveRef(resolved);
                              setActiveMessageRefs(m.references ?? [resolved]);
                              setActiveClaimText(claimText ?? null);
                              setPdfDocId(resolved.document_id ?? documentIds[0] ?? null);
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
                );
              })}
              {showActivityPanel && (
                <RetrievalActivityPanel
                  steps={activity.steps}
                  stepCount={activity.stepCount}
                  isStreaming={streaming}
                  shouldMinimize={activity.shouldMinimize}
                  retrievalSummary={activity.retrievalSummary}
                  elapsedMs={requestTimer.elapsedMs}
                />
              )}
              {showAgentToolsPanel ? (
                <div className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2">
                  <ToolTimeline steps={agentActivity.toolSteps} />
                </div>
              ) : null}
            </div>
            <div className="border-t border-neutral-200 px-4 pt-3">
              <PiiInfoBanner
                visible={
                  !!appSettings &&
                  appSettings.llm_provider !== "ollama" &&
                  piiEnabled &&
                  !piiInfoDismissed
                }
                onDismiss={() => {
                  localStorage.setItem(PII_INFO_DISMISSED_KEY, "true");
                  setPiiInfoDismissed(true);
                }}
              />
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
        )}
      </div>
    </div>
  );
}
