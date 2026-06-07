"use client";

import type { ChatSessionSummary } from "@/lib/picardApi";

type Props = {
  workspaceName: string;
  docCount: number;
  sessions: ChatSessionSummary[];
  onSelectSession: (id: string) => void;
  onSuggestedQuestion: (q: string) => void;
  onUploadClick: () => void;
};

const SUGGESTIONS = [
  "What are the key obligations in these documents?",
  "Summarize the parties and their roles.",
  "What termination provisions apply?",
];

export function WelcomeState({
  workspaceName,
  docCount,
  sessions,
  onSelectSession,
  onSuggestedQuestion,
  onUploadClick,
}: Props) {
  return (
    <div className="mx-auto max-w-lg space-y-8 py-12 text-center">
      <div>
        <h2
          className="font-serif text-2xl text-neutral-900"
          style={{ fontFamily: "var(--font-garamond), serif" }}
        >
          {workspaceName}
        </h2>
        <p className="mt-2 text-sm text-neutral-500">
          {docCount === 0
            ? "No documents indexed yet. Upload PDFs to get started."
            : `${docCount} document${docCount === 1 ? "" : "s"} ready for Q&A`}
        </p>
      </div>

      <div className="flex flex-wrap justify-center gap-2">
        <button
          type="button"
          onClick={onUploadClick}
          className="composer-pill hover:bg-neutral-100"
        >
          Upload documents
        </button>
        {SUGGESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onSuggestedQuestion(q)}
            className="composer-pill max-w-xs truncate hover:bg-neutral-100"
            title={q}
          >
            {q}
          </button>
        ))}
      </div>

      {sessions.length > 0 ? (
        <div className="text-left">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
            Recent chats
          </p>
          <ul className="space-y-1">
            {sessions.slice(0, 5).map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => onSelectSession(s.id)}
                  className="w-full truncate rounded-md px-2 py-1.5 text-left text-sm text-neutral-700 hover:bg-neutral-100"
                >
                  {s.title || s.preview || "Untitled chat"}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
