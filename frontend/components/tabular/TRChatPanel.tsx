"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, MessageSquare, X } from "lucide-react";
import type { ChatMessage, TabularReview } from "@/lib/picardApi";
import { picardApi } from "@/lib/picardApi";
import { parseCellRefs } from "./citation-utils";
import { Button } from "@/components/ui/button";

type Props = {
  review: TabularReview;
  workspaceId: string;
  onClose: () => void;
  onCellRefClick?: (columnKey: string, documentId: string) => void;
};

function renderContentWithCellRefs(
  content: string,
  onCellRefClick?: (columnKey: string, documentId: string) => void
) {
  const parts = content.split(/(\[\[cell:[^\]]+\]\])/g);
  return parts.map((part, i) => {
    const refs = parseCellRefs(part);
    if (refs.length === 1) {
      const { column_key, document_id } = refs[0];
      const col = part;
      return (
        <button
          key={i}
          type="button"
          className="mx-0.5 rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-800 hover:bg-blue-200"
          onClick={() => onCellRefClick?.(column_key, document_id)}
        >
          cell
        </button>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

export function TRChatPanel({ review, workspaceId, onClose, onCellRefClick }: Props) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    picardApi
      .createChatSession({
        workspace_id: workspaceId,
        title: `Tabular: ${review.title}`,
      })
      .then((s) => {
        if (!cancelled) setSessionId(s.id);
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId, review.title]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamText]);

  async function send() {
    if (!sessionId || !input.trim() || streaming) return;
    const text = input.trim();
    setInput("");
    setMessages((m) => [
      ...m,
      {
        id: `u-${Date.now()}`,
        session_id: sessionId,
        role: "user",
        content: text,
        refused: false,
        created_at: new Date().toISOString(),
      },
    ]);
    setStreaming(true);
    setStreamText("");
    let assistant = "";
    let finalized = false;
    try {
      for await (const ev of picardApi.streamChat({
        session_id: sessionId,
        workspace_id: workspaceId,
        message: text,
        document_ids: review.document_ids,
        tabular_review_id: review.id,
      })) {
        if (ev.event === "content" && "delta" in ev) {
          assistant += ev.delta;
          setStreamText(assistant);
        }
        if (ev.event === "references" && "references" in ev) {
          finalized = true;
          setMessages((m) => [
            ...m,
            {
              id: `a-${Date.now()}`,
              session_id: sessionId,
              role: "assistant",
              content: assistant,
              references: ev.references,
              refused: Boolean(ev.refused),
              created_at: new Date().toISOString(),
            },
          ]);
          setStreamText("");
        }
      }
      if (!finalized && assistant) {
        setMessages((m) => [
          ...m,
          {
            id: `a-${Date.now()}`,
            session_id: sessionId,
            role: "assistant",
            content: assistant,
            refused: false,
            created_at: new Date().toISOString(),
          },
        ]);
        setStreamText("");
      }
    } catch (err) {
      setMessages((m) => [
        ...m,
        {
          id: `e-${Date.now()}`,
          session_id: sessionId,
          role: "assistant",
          content: `Error: ${err instanceof Error ? err.message : "Chat failed"}`,
          refused: true,
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setStreaming(false);
    }
  }

  return (
    <div className="flex h-full w-[360px] shrink-0 flex-col border-l border-neutral-200 bg-white">
      <div className="flex items-center gap-2 border-b border-neutral-200 px-3 py-2">
        <MessageSquare className="h-4 w-4 text-neutral-500" />
        <span className="flex-1 truncate text-sm font-medium">Review chat</span>
        <button type="button" onClick={onClose} className="rounded p-1 hover:bg-neutral-100">
          <X className="h-4 w-4" />
        </button>
      </div>
      <p className="border-b border-neutral-100 px-3 py-2 text-[10px] text-neutral-500">
        Ask about this table. Assistant may cite cells as [[cell:column_key:document_id]].
      </p>
      <div className="flex-1 overflow-y-auto p-3 text-sm">
        {messages.map((m) => (
          <div
            key={m.id}
            className={`mb-3 ${m.role === "user" ? "text-right" : ""}`}
          >
            <div
              className={`inline-block max-w-[95%] rounded px-2 py-1.5 text-left ${
                m.role === "user" ? "bg-neutral-900 text-white" : "bg-neutral-100 text-neutral-900"
              }`}
            >
              {m.role === "assistant"
                ? renderContentWithCellRefs(m.content, onCellRefClick)
                : m.content}
            </div>
          </div>
        ))}
        {streamText ? (
          <div className="mb-3 rounded bg-neutral-100 px-2 py-1.5 text-neutral-900">
            {renderContentWithCellRefs(streamText, onCellRefClick)}
          </div>
        ) : null}
        {streaming && !streamText ? (
          <Loader2 className="h-4 w-4 animate-spin text-neutral-400" />
        ) : null}
        <div ref={bottomRef} />
      </div>
      <div className="border-t border-neutral-200 p-3">
        <textarea
          className="mb-2 w-full resize-none rounded border border-neutral-300 px-2 py-1.5 text-sm"
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Ask about this review…"
          disabled={!sessionId || streaming}
        />
        <Button size="sm" className="w-full" disabled={!sessionId || streaming} onClick={send}>
          Send
        </Button>
      </div>
    </div>
  );
}
