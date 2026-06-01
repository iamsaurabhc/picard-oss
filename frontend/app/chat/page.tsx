"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  picardApi,
  ChatMessage,
  ChatReference,
  ChatStreamEvent,
} from "@/lib/picardApi";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FormSelect } from "@/components/FormSelect";
import { DocumentMultiSelect } from "@/components/DocumentMultiSelect";
import { MarkdownWithCitations } from "@/components/MarkdownWithCitations";
import { RetrievalActivityPanel } from "@/components/chat/RetrievalActivityPanel";
import { useRetrievalActivity } from "@/components/chat/useRetrievalActivity";
import { MultiHighlightPDFViewer } from "@/components/MultiHighlightPDFViewer";
import { cn } from "@/lib/utils";

type UiMessage = {
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

export default function ChatPage() {
  const [workspaceId, setWorkspaceId] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [documentIds, setDocumentIds] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [activeRef, setActiveRef] = useState<ChatReference | null>(null);
  const [activeMessageRefs, setActiveMessageRefs] = useState<ChatReference[] | null>(null);
  const [pdfDocId, setPdfDocId] = useState<string | null>(null);
  const streamingRef = useRef(false);
  const activity = useRetrievalActivity();

  const { data: workspaces } = useQuery({
    queryKey: ["workspaces"],
    queryFn: picardApi.listWorkspaces,
  });

  const ws = workspaceId || workspaces?.[0]?.id || "";

  const { data: documents } = useQuery({
    queryKey: ["documents", ws],
    queryFn: () => picardApi.listDocuments(ws),
    enabled: !!ws,
  });

  useEffect(() => {
    if (!ws || sessionId) return;
    picardApi.createChatSession({ workspace_id: ws, title: "Assistant" }).then((s) => {
      setSessionId(s.id);
    });
  }, [ws, sessionId]);

  const loadHistory = useCallback(async () => {
    if (!sessionId || streamingRef.current) return;
    const hist = await picardApi.listChatMessages(sessionId);
    setMessages(
      hist.map((m: ChatMessage) => ({
        role: m.role,
        content: m.content,
        references: m.references ?? undefined,
        refused: m.refused,
      }))
    );
  }, [sessionId]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

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

  return (
    <div className="flex h-[calc(100vh)] flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-neutral-200 bg-white px-4 py-3">
        <h1
          className="shrink-0 font-serif text-2xl"
          style={{ fontFamily: "var(--font-garamond), serif" }}
        >
          Chat
        </h1>
        <FormSelect
          className="shrink-0"
          value={ws}
          onChange={(e) => {
            setWorkspaceId(e.target.value);
            setSessionId(null);
            setDocumentIds([]);
            setPdfDocId(null);
            setActiveRef(null);
            setActiveMessageRefs(null);
            activity.reset();
          }}
        >
          {(workspaces ?? []).map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </FormSelect>
        <DocumentMultiSelect
          documents={(documents ?? []).map((d) => ({ id: d.id, file_name: d.file_name }))}
          selectedIds={documentIds}
          onChange={setDocumentIds}
        />
      </header>

      <div
        className={cn(
          "grid flex-1 overflow-hidden",
          showPdfPanel && "grid-cols-2 divide-x divide-neutral-200"
        )}
      >
        <div className="flex flex-col overflow-hidden">
          <div className="flex-1 space-y-4 overflow-y-auto p-4">
            {messages.map((m, i) => (
              <div
                key={i}
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
                    <MarkdownWithCitations
                      text={m.content}
                      references={m.references}
                      onCitationClick={(ref) => {
                        setActiveRef(ref);
                        setActiveMessageRefs(m.references ?? []);
                        setPdfDocId(ref.document_id);
                      }}
                    />
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
              disabled={streaming || !sessionId}
            />
            <Button type="submit" disabled={streaming || !sessionId}>
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
  );
}
