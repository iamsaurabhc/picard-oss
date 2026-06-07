"use client";

import { useState } from "react";
import { History, MessageSquarePlus, PanelLeft, Trash2 } from "lucide-react";
import type { ChatSessionSummary } from "@/lib/picardApi";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Props = {
  sessions: ChatSessionSummary[];
  activeId: string | null;
  loading?: boolean;
  disabled?: boolean;
  collapsed: boolean;
  mobileOverlay?: boolean;
  onToggleCollapse: () => void;
  onSelect: (sessionId: string) => void;
  onNewChat: () => void;
  onDelete?: (sessionId: string) => void;
};

function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const diffMs = Date.now() - date.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString();
}

function SessionList({
  sessions,
  activeId,
  loading,
  disabled,
  onSelect,
  onDelete,
}: {
  sessions: ChatSessionSummary[];
  activeId: string | null;
  loading?: boolean;
  disabled?: boolean;
  onSelect: (sessionId: string) => void;
  onDelete?: (sessionId: string) => void;
}) {
  const [deleteTarget, setDeleteTarget] = useState<ChatSessionSummary | null>(null);

  return (
    <>
      <div className="flex-1 overflow-y-auto p-2">
        {loading ? (
          <p className="px-2 py-4 text-xs text-neutral-500">Loading chats…</p>
        ) : sessions.length === 0 ? (
          <p className="px-2 py-4 text-xs text-neutral-500">No chats yet.</p>
        ) : (
          <ul className="space-y-1">
            {sessions.map((s) => {
              const active = s.id === activeId;
              return (
                <li key={s.id}>
                  <div
                    className={cn(
                      "group flex items-start gap-1 rounded-md",
                      active && "bg-white shadow-sm ring-1 ring-neutral-200"
                    )}
                  >
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => onSelect(s.id)}
                      className={cn(
                        "min-w-0 flex-1 rounded-md px-2 py-2 text-left text-sm transition-colors",
                        !active && "hover:bg-neutral-100",
                        disabled && "opacity-50"
                      )}
                    >
                      <div className="truncate font-medium text-neutral-900">
                        {s.title?.trim() || "New chat"}
                      </div>
                      {s.preview ? (
                        <div className="mt-0.5 truncate text-xs text-neutral-500">{s.preview}</div>
                      ) : null}
                      {s.has_user_message ? (
                        <div className="mt-1 text-[10px] text-neutral-400">
                          {formatRelativeTime(s.updated_at)}
                          {s.message_count > 0 ? ` · ${s.message_count} msgs` : ""}
                        </div>
                      ) : null}
                    </button>
                    {onDelete ? (
                      <button
                        type="button"
                        title="Delete chat"
                        aria-label="Delete chat"
                        disabled={disabled}
                        onClick={() => setDeleteTarget(s)}
                        className="mr-1 mt-2 rounded p-1 text-neutral-400 opacity-0 transition-opacity hover:bg-neutral-200 hover:text-red-700 group-hover:opacity-100"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {deleteTarget && onDelete ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30 p-4">
          <div className="w-full max-w-sm rounded-lg bg-white p-6 shadow-lg">
            <h2 className="mb-2 font-serif text-lg">Delete chat?</h2>
            <p className="mb-4 text-sm text-neutral-600">
              <span className="font-medium text-neutral-900">
                {deleteTarget.title?.trim() || "New chat"}
              </span>{" "}
              and all messages will be removed.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDeleteTarget(null)}>
                Cancel
              </Button>
              <Button
                className="bg-red-700 text-white hover:bg-red-800"
                onClick={() => {
                  onDelete(deleteTarget.id);
                  setDeleteTarget(null);
                }}
              >
                Delete
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

export function ChatHistoryRail({
  sessions,
  activeId,
  loading,
  disabled,
  collapsed,
  mobileOverlay = false,
  onToggleCollapse,
  onSelect,
  onNewChat,
  onDelete,
}: Props) {
  if (collapsed && !mobileOverlay) {
    return (
      <aside className="flex h-full w-12 shrink-0 flex-col items-center gap-2 border-r border-neutral-200 bg-neutral-50 py-3">
        <button
          type="button"
          title="New chat"
          aria-label="New chat"
          disabled={disabled}
          onClick={onNewChat}
          className="flex h-9 w-9 items-center justify-center rounded-md border border-neutral-200 bg-white text-neutral-700 transition-colors hover:bg-neutral-100 disabled:opacity-50"
        >
          <MessageSquarePlus className="h-4 w-4" />
        </button>
        <button
          type="button"
          title="Chat history"
          aria-label="Expand chat history"
          disabled={disabled}
          onClick={onToggleCollapse}
          className="flex h-9 w-9 items-center justify-center rounded-md text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-800 disabled:opacity-50"
        >
          <PanelLeft className="h-4 w-4" />
        </button>
      </aside>
    );
  }

  return (
    <aside
      className={cn(
        "flex h-full w-60 shrink-0 flex-col border-r border-neutral-200 bg-neutral-50",
        mobileOverlay && "shadow-lg"
      )}
    >
      <div className="flex items-center gap-2 border-b border-neutral-200 p-3">
        <Button
          type="button"
          variant="outline"
          className="min-w-0 flex-1 justify-start gap-2 bg-white"
          onClick={onNewChat}
          disabled={disabled}
        >
          <MessageSquarePlus className="h-4 w-4 shrink-0" />
          New chat
        </Button>
        {!mobileOverlay ? (
          <button
            type="button"
            title="Collapse history"
            aria-label="Collapse chat history"
            onClick={onToggleCollapse}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-neutral-500 hover:bg-neutral-100 hover:text-neutral-800"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
        ) : (
          <button
            type="button"
            title="Close history"
            aria-label="Close chat history"
            onClick={onToggleCollapse}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-neutral-500 hover:bg-neutral-100 hover:text-neutral-800"
          >
            <History className="h-4 w-4" />
          </button>
        )}
      </div>

      <SessionList
        sessions={sessions}
        activeId={activeId}
        loading={loading}
        disabled={disabled}
        onSelect={onSelect}
        onDelete={onDelete}
      />
    </aside>
  );
}
