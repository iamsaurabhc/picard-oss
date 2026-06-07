"use client";

import Link from "next/link";
import { MarkdownWithCitations } from "@/components/MarkdownWithCitations";
import { resolveCitationForClaim } from "@/lib/citationAnchor";
import type { ChatReference } from "@/lib/picardApi";
import type { UnifiedMessage } from "@/lib/unifiedChatTypes";
import { cn } from "@/lib/utils";

type Props = {
  message: UnifiedMessage;
  onCitationClick?: (ref: ChatReference, refs: ChatReference[]) => void;
};

export function MessageRenderer({ message, onCitationClick }: Props) {
  switch (message.type) {
    case "user_text":
      return (
        <div className="flex justify-end message-enter">
          <div className="message-bubble message-bubble-user">
            {message.content}
            {message.attachmentNames?.length ? (
              <p className="mt-1 text-xs opacity-70">
                + {message.attachmentNames.join(", ")}
              </p>
            ) : null}
          </div>
        </div>
      );

    case "assistant_qa":
      return (
        <div className="flex justify-start message-enter">
          <div className="message-bubble message-bubble-assistant">
            {message.refused ? (
              <p className="text-neutral-700">{message.content}</p>
            ) : (
              <MarkdownWithCitations
                text={message.content}
                references={message.references ?? []}
                onCitationClick={(ref, claimText) => {
                  const resolved = resolveCitationForClaim(
                    ref,
                    claimText,
                    message.references ?? undefined
                  );
                  onCitationClick?.(resolved, message.references ?? []);
                }}
              />
            )}
            {message.suggestions?.length ? (
              <ul className="mt-2 space-y-1 text-xs text-neutral-600">
                {message.suggestions.map((s) => (
                  <li key={s}>• {s}</li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>
      );

    case "indexing_notice":
      return (
        <div className="flex justify-center message-enter">
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
            Indexing {message.documents.length} document
            {message.documents.length === 1 ? "" : "s"} before answering…
          </div>
        </div>
      );

    case "tabular_preview":
      return (
        <div className="flex justify-start message-enter">
          <div className="message-bubble message-bubble-assistant">
            <p className="font-medium">Tabular review created</p>
            <p className="mt-1 text-neutral-600">
              {message.title} · {message.columnCount} columns
            </p>
            <Link
              href={`/tabular/${message.reviewId}`}
              className="mt-2 inline-block text-sm text-blue-600 hover:underline"
            >
              Open full review →
            </Link>
          </div>
        </div>
      );

    case "error":
      return (
        <div className="flex justify-start message-enter message-shake">
          <div className="message-bubble border-red-200 bg-red-50 text-red-900">
            <p>{message.detail}</p>
            {message.retry ? (
              <button
                type="button"
                className="mt-2 text-sm font-medium underline"
                onClick={message.retry}
              >
                Retry
              </button>
            ) : null}
          </div>
        </div>
      );

    default:
      return null;
  }
}

export function MessageList({
  messages,
  onCitationClick,
  streaming,
}: {
  messages: UnifiedMessage[];
  onCitationClick?: (ref: ChatReference, refs: ChatReference[]) => void;
  streaming?: boolean;
}) {
  return (
    <div className="space-y-4">
      {messages.map((m, i) => {
        if (m.type === "assistant_qa" && !m.content && streaming) return null;
        const key = m.id ?? `${m.type}-${i}`;
        return <MessageRenderer key={key} message={m} onCitationClick={onCitationClick} />;
      })}
    </div>
  );
}
