"use client";

import { useCallback, useRef } from "react";
import { publishDocxSuggestion } from "@/lib/docxSuggestionStore";
import { picardApi, type ChatStreamEvent } from "@/lib/picardApi";

export type StreamResult = {
  content: string;
  references?: import("@/lib/picardApi").ChatReference[];
  refused?: boolean;
  suggestions?: string[];
};

export function useChatStream(onEvent?: (ev: ChatStreamEvent) => void) {
  const bufferRef = useRef("");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const runStream = useCallback(
    async (
      body: Parameters<typeof picardApi.streamChat>[0],
      onDelta: (accumulated: string) => void
    ): Promise<StreamResult> => {
      let assistant = "";
      let refs: import("@/lib/picardApi").ChatReference[] = [];
      let refused = false;
      let suggestions: string[] = [];
      let streamBuffer = "";

      const flush = () => {
        if (!streamBuffer) return;
        assistant += streamBuffer;
        streamBuffer = "";
        onDelta(assistant);
      };

      const scheduleFlush = () => {
        if (timerRef.current) return;
        timerRef.current = setTimeout(() => {
          timerRef.current = null;
          flush();
        }, 75);
      };

      for await (const ev of picardApi.streamChat(body, onEvent)) {
        if (ev.event === "error") {
          const msg = ("detail" in ev && ev.detail) || ("message" in ev && ev.message) || "Error";
          throw new Error(String(msg));
        }
        if (ev.event === "content" && "delta" in ev) {
          streamBuffer += ev.delta;
          scheduleFlush();
        } else if (ev.event === "docx_suggestion") {
          publishDocxSuggestion({
            document_id: ev.document_id,
            find: ev.find,
            replace: ev.replace,
            change_mode: ev.change_mode,
            rationale: ev.rationale,
          });
        } else if (ev.event === "references") {
          if (timerRef.current) {
            clearTimeout(timerRef.current);
            timerRef.current = null;
          }
          flush();
          refs = ev.references ?? [];
          if (typeof ev.content === "string" && ev.content.length > 0) assistant = ev.content;
          refused = !!ev.refused;
          suggestions = ev.suggestions ?? [];
          onDelta(assistant);
        }
      }
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      flush();

      return {
        content: assistant,
        references: refused ? undefined : refs,
        refused,
        suggestions: refused ? suggestions : undefined,
      };
    },
    [onEvent]
  );

  return { runStream };
}
