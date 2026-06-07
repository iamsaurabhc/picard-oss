"use client";

import { useCallback, useEffect, useRef } from "react";
import { Loader2, Mic, Send } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AttachedDocument, ComposerMode } from "@/lib/unifiedChatTypes";
import { attachmentsIndexing, attachmentsReadyCount } from "@/lib/unifiedChatTypes";
import { AddContextMenu } from "./AddContextMenu";
import { AttachmentChipRow } from "./AttachmentChipRow";
import { ModeSelectorPill } from "./ModeSelectorPill";
import { PromptGuideTip } from "./PromptGuideTip";

type Props = {
  input: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onUpload: (files: FileList | File[]) => void;
  onBrowseVault?: () => void;
  mode: ComposerMode;
  onModeChange: (mode: ComposerMode) => void;
  attachments: AttachedDocument[];
  onRemoveAttachment: (id: string) => void;
  isStreaming: boolean;
  disabled?: boolean;
  uploadRequestId?: number;
};

export function ChatComposer({
  input,
  onInputChange,
  onSend,
  onUpload,
  onBrowseVault,
  mode,
  onModeChange,
  attachments,
  onRemoveAttachment,
  isStreaming,
  disabled,
  uploadRequestId,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const indexing = attachmentsIndexing(attachments);
  const { ready, total } = attachmentsReadyCount(attachments);
  const sendBlocked = disabled || isStreaming;
  const canSend =
    !sendBlocked && (input.trim().length > 0 || mode === "review");

  const adjustHeight = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, []);

  useEffect(() => {
    adjustHeight();
  }, [input, adjustHeight]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "u") {
        e.preventDefault();
        onUpload([]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onUpload]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!sendBlocked && (input.trim() || mode === "review")) onSend();
    }
  };

  const sendLabel = indexing && total > 0 ? `Indexing ${ready}/${total}…` : "Send";

  return (
    <div className="composer-card mx-auto w-full max-w-3xl">
      <AttachmentChipRow attachments={attachments} onRemove={onRemoveAttachment} />
      <div className="relative">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            mode === "review"
              ? "Optional title or instructions for the review…"
              : "Ask about your documents…"
          }
          disabled={disabled || isStreaming}
          rows={1}
          className="w-full resize-none bg-transparent py-3 pl-4 pr-9 text-sm outline-none placeholder:text-neutral-400"
        />
        <PromptGuideTip mode={mode} disabled={disabled || isStreaming} />
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-neutral-100 px-3 py-2">
        <div className="flex items-center gap-2">
          <AddContextMenu
            onUpload={onUpload}
            onBrowseVault={onBrowseVault}
            disabled={disabled || isStreaming}
            uploadRequestId={uploadRequestId}
          />
          <ModeSelectorPill
            mode={mode}
            onChange={onModeChange}
            disabled={disabled || isStreaming}
          />
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="composer-pill hidden h-8 w-8 items-center justify-center rounded-full p-0 sm:flex"
            aria-label="Voice input"
            title="Voice input (coming soon)"
            disabled
          >
            <Mic className="h-4 w-4 opacity-40" />
          </button>
          <button
            type="button"
            onClick={onSend}
            disabled={!canSend}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white transition-opacity hover:bg-neutral-800",
              !canSend && "opacity-50"
            )}
          >
            {isStreaming || indexing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
            <span className="hidden sm:inline">{sendLabel}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
