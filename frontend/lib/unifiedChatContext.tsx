"use client";

import {
  createContext,
  useContext,
  type ReactNode,
} from "react";
import type {
  AttachedDocument,
  ComposerMode,
  UnifiedMessage,
} from "@/lib/unifiedChatTypes";
import type { TabularTemplateId } from "@/lib/tabular/columnPresets";
import type { ChatReference } from "@/lib/picardApi";

/** Shared types for unified chat state (logic lives in UnifiedChatContainer). */
export type UnifiedChatState = {
  sessionId: string | null;
  messages: UnifiedMessage[];
  attachments: AttachedDocument[];
  documentIds: string[];
  mode: ComposerMode;
  reviewTemplateId: TabularTemplateId;
  isStreaming: boolean;
  isIndexing: boolean;
  pdfPanelOpen: boolean;
  activeRef: ChatReference | null;
};

const UnifiedChatContext = createContext<UnifiedChatState | null>(null);

export function UnifiedChatProvider({
  children,
  value,
}: {
  children: ReactNode;
  value: UnifiedChatState;
}) {
  return (
    <UnifiedChatContext.Provider value={value}>{children}</UnifiedChatContext.Provider>
  );
}

export function useUnifiedChat() {
  const ctx = useContext(UnifiedChatContext);
  if (!ctx) throw new Error("useUnifiedChat must be used within UnifiedChatProvider");
  return ctx;
}
