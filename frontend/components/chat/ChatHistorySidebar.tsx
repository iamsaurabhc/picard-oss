"use client";

import { useState } from "react";
import { MessageSquarePlus, Trash2 } from "lucide-react";
import type { ChatSessionSummary } from "@/lib/picardApi";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Props = {
  sessions: ChatSessionSummary[];
  activeId: string | null;
  loading?: boolean;
  disabled?: boolean;
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

export function ChatHistorySidebar({
  sessions,
  activeId,
  loading,
  disabled,
  onSelect,
  onNewChat,
  onDelete,
}: Props) {
  const [deleteTarget, setDeleteTarget] = useState<ChatSessionSummary | null>(null);

  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-neutral-200 bg-neutral-50">
      <div className="border-b border-neutral-200 p-3">
        <Button
          type="button"
          variant="outline"
          className="w-full justify-start gap-2 bg-white"
          onClick={onNewChat}
          disabled={disabled}
        >
          <MessageSquarePlus className="h-4 w-4" />
          New chat
        </Button>
      </div>

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
    </aside>
  );
}
